"""OBLM-Live: online Order Book Language Model components.

This module provides:
- Async dual-stream market data ingestion (L2 + 1m candles)
- Minute-level stream synchronization into MarketState
- Adaptive quantization into language-like tokens
- Incremental SGD-based directional model with 5-minute delayed supervision
- Calibration tracking via Expected Calibration Error (ECE)
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import logging
import math
import pickle
import signal
import sys
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Awaitable, Callable

try:
    import websockets
except ImportError:  # pragma: no cover - allows offline/unit-test imports without ws deps
    websockets = None  # type: ignore[assignment]

try:
    from sklearn.feature_extraction.text import HashingVectorizer
    from sklearn.linear_model import SGDClassifier

    _SKLEARN_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised in environments without sklearn
    HashingVectorizer = None  # type: ignore[assignment]
    SGDClassifier = None  # type: ignore[assignment]
    _SKLEARN_AVAILABLE = False

logger = logging.getLogger(__name__)


def _load_oblm_memory_components() -> tuple[type, type]:
    """Load memory layer classes without importing package-level __init__.

    Using direct module loading avoids pulling optional runtime dependencies from
    `src.trading.__init__` during lightweight/unit test imports.
    """
    module_path = Path(__file__).with_name("oblm_memory.py")
    spec = importlib.util.spec_from_file_location("oblm_memory_runtime", module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load memory module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.MemoryDecisionGate, module.SimilarStateMemory


def _configure_decision_log_file(
    decision_log_path: str,
    max_bytes: int,
    backup_count: int,
) -> logging.Logger:
    """Configure rolling decision-only log output.

    This logger writes only OBLM decision lines and rotates by file size,
    keeping a short rolling window of recent history on disk.
    """
    decision_logger = logging.getLogger(f"{__name__}.decision")
    decision_logger.setLevel(logging.INFO)
    decision_logger.propagate = False

    log_path = Path(decision_log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.touch(exist_ok=True)
    resolved = str(log_path.resolve())

    # Avoid adding duplicate handlers when function is called multiple times.
    for handler in decision_logger.handlers:
        if isinstance(handler, RotatingFileHandler):
            if Path(handler.baseFilename).resolve() == log_path.resolve():
                return decision_logger

    file_handler = RotatingFileHandler(
        filename=resolved,
        maxBytes=max(1024, int(max_bytes)),
        backupCount=max(1, int(backup_count)),
        encoding="utf-8",
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    )
    decision_logger.addHandler(file_handler)
    return decision_logger


def _configure_confidence_log_file(
    confidence_log_path: str,
    max_bytes: int,
    backup_count: int,
) -> logging.Logger:
    """Configure rolling confidence-winrate log output."""
    confidence_logger = logging.getLogger(f"{__name__}.confidence")
    confidence_logger.setLevel(logging.INFO)
    confidence_logger.propagate = False

    log_path = Path(confidence_log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.touch(exist_ok=True)
    resolved = str(log_path.resolve())

    for handler in confidence_logger.handlers:
        if isinstance(handler, RotatingFileHandler):
            if Path(handler.baseFilename).resolve() == log_path.resolve():
                return confidence_logger

    file_handler = RotatingFileHandler(
        filename=resolved,
        maxBytes=max(1024, int(max_bytes)),
        backupCount=max(1, int(backup_count)),
        encoding="utf-8",
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    )
    confidence_logger.addHandler(file_handler)
    return confidence_logger


def _configure_memory_log_file(
    memory_log_path: str,
    max_bytes: int,
    backup_count: int,
) -> logging.Logger:
    """Configure rolling similar-state-memory log output."""
    memory_logger = logging.getLogger(f"{__name__}.memory")
    memory_logger.setLevel(logging.INFO)
    memory_logger.propagate = False

    log_path = Path(memory_log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.touch(exist_ok=True)
    resolved = str(log_path.resolve())

    for handler in memory_logger.handlers:
        if isinstance(handler, RotatingFileHandler):
            if Path(handler.baseFilename).resolve() == log_path.resolve():
                return memory_logger

    file_handler = RotatingFileHandler(
        filename=resolved,
        maxBytes=max(1024, int(max_bytes)),
        backupCount=max(1, int(backup_count)),
        encoding="utf-8",
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    )
    memory_logger.addHandler(file_handler)
    return memory_logger


def _log_memory_event(memory_logger: logging.Logger, event: str, **fields: object) -> None:
    payload = " ".join(
        f"{key}={value}"
        for key, value in fields.items()
        if value is not None
    )
    if payload:
        memory_logger.info("MEMORY event=%s %s", event, payload)
        return
    memory_logger.info("MEMORY event=%s", event)


def _trim_log_to_last_lines(log_path: str, max_lines: int) -> None:
    """Keep only the latest max_lines lines in a log file."""
    keep = max(1, int(max_lines))
    path = Path(log_path)
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as f:
        lines = f.readlines()
    if len(lines) <= keep:
        return
    with path.open("w", encoding="utf-8") as f:
        f.writelines(lines[-keep:])


def _log_lifecycle(
    decision_logger: logging.Logger,
    phase: str,
    **fields: object,
) -> None:
    """Write a structured lifecycle event to the decision log."""
    payload = " ".join(
        f"{key}={value}"
        for key, value in fields.items()
        if value is not None
    )
    if payload:
        decision_logger.info("LIFECYCLE phase=%s %s", phase, payload)
        return
    decision_logger.info("LIFECYCLE phase=%s", phase)


def _utc_from_ms(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def _minute_floor(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.replace(second=0, microsecond=0)


@dataclass
class L2Snapshot:
    """Top-of-book depth snapshot."""

    timestamp: datetime
    bids: list[tuple[float, float]]
    asks: list[tuple[float, float]]


@dataclass
class Candle1m:
    """One-minute OHLCV candle."""

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class MarketState:
    """Synchronized L2 + candle market state."""

    timestamp: datetime
    l2: L2Snapshot
    candle: Candle1m


@dataclass
class PredictionOutput:
    """Structured OBLM prediction output."""

    direction: str
    probability: float
    timestamp: str


@dataclass
class PendingPrediction:
    """Prediction awaiting 5-minute realized outcome."""

    minute: datetime
    token: str
    reference_price: float
    predicted_direction: str
    bull_probability: float


class MinuteMarketStateSynchronizer:
    """Synchronize L2 and 1m candle streams on minute buckets."""

    def __init__(self, max_bucket_age_minutes: int = 10):
        self._l2_by_minute: dict[datetime, L2Snapshot] = {}
        self._candle_by_minute: dict[datetime, Candle1m] = {}
        self._emitted_by_minute: dict[datetime, datetime] = {}
        self._max_age = timedelta(minutes=max_bucket_age_minutes)

    def add_l2(self, snapshot: L2Snapshot) -> MarketState | None:
        minute = _minute_floor(snapshot.timestamp)
        self._l2_by_minute[minute] = snapshot
        return self._try_emit(minute)

    def add_candle(self, candle: Candle1m) -> MarketState | None:
        minute = _minute_floor(candle.timestamp)
        self._candle_by_minute[minute] = candle
        return self._try_emit(minute)

    def _try_emit(self, minute: datetime) -> MarketState | None:
        self._cleanup(minute)
        if minute not in self._l2_by_minute or minute not in self._candle_by_minute:
            return None

        # Emit at most once per minute bucket to satisfy minute-cadence output.
        if minute in self._emitted_by_minute:
            self._l2_by_minute.pop(minute, None)
            self._candle_by_minute.pop(minute, None)
            return None

        l2 = self._l2_by_minute.pop(minute)
        candle = self._candle_by_minute.pop(minute)
        self._emitted_by_minute[minute] = minute
        return MarketState(timestamp=minute, l2=l2, candle=candle)

    def _cleanup(self, current_minute: datetime) -> None:
        cutoff = current_minute - self._max_age
        self._l2_by_minute = {
            minute: snapshot
            for minute, snapshot in self._l2_by_minute.items()
            if minute >= cutoff
        }
        self._candle_by_minute = {
            minute: candle
            for minute, candle in self._candle_by_minute.items()
            if minute >= cutoff
        }
        self._emitted_by_minute = {
            minute: value
            for minute, value in self._emitted_by_minute.items()
            if minute >= cutoff
        }


class _RollingStats:
    def __init__(self, window: int):
        self._window = max(5, window)
        self._values: deque[float] = deque(maxlen=self._window)
        self._sum = 0.0
        self._sum_sq = 0.0

    def update(self, value: float) -> None:
        if len(self._values) == self._values.maxlen:
            old = self._values[0]
            self._sum -= old
            self._sum_sq -= old * old
        self._values.append(value)
        self._sum += value
        self._sum_sq += value * value

    @property
    def mean(self) -> float:
        n = len(self._values)
        return self._sum / n if n else 0.0

    @property
    def std(self) -> float:
        n = len(self._values)
        if n < 2:
            return 0.0
        var = max((self._sum_sq / n) - (self.mean**2), 0.0)
        return math.sqrt(var)

    def zscore(self, value: float) -> float:
        sigma = self.std
        if sigma <= 1e-12:
            return 0.0
        return (value - self.mean) / sigma

    def dump_state(self) -> dict:
        return {
            "window": self._window,
            "values": list(self._values),
        }

    @classmethod
    def from_state(cls, state: dict) -> "_RollingStats":
        obj = cls(window=int(state.get("window", 240)))
        for value in state.get("values", []):
            obj.update(float(value))
        return obj


class AdaptiveQuantizer:
    """Adaptive microstructure quantizer with rolling volatility-aware bins."""

    _FEATURES = (
        "imbalance",
        "spread",
        "depth",
        "body_size",
        "wick_ratio",
        "relative_volume",
    )

    def __init__(self, rolling_window: int = 240):
        self._stats = {name: _RollingStats(rolling_window) for name in self._FEATURES}

    @staticmethod
    def _bucket_generic(z: float) -> str:
        if z < -1.25:
            return "VLOW"
        if z < -0.35:
            return "LOW"
        if z < 0.35:
            return "MID"
        if z < 1.25:
            return "HIGH"
        return "VHIGH"

    @staticmethod
    def _bucket_spread(z: float) -> str:
        if z < -0.8:
            return "TIGHT"
        if z < 0.8:
            return "NORM"
        return "WIDE"

    @staticmethod
    def _bucket_body(z: float) -> str:
        if z < -0.8:
            return "SHORT"
        if z < 0.8:
            return "MID"
        return "LONG"

    @staticmethod
    def _bucket_wick(z: float) -> str:
        if z < -0.8:
            return "LOW"
        if z < 0.8:
            return "MID"
        return "HIGH"

    @staticmethod
    def _candle_direction(open_price: float, close_price: float) -> str:
        if close_price > open_price:
            return "BULL"
        if close_price < open_price:
            return "BEAR"
        return "DOJI"

    def _extract_features(self, state: MarketState) -> dict[str, float]:
        bids = state.l2.bids[:20]
        asks = state.l2.asks[:20]
        bid_qty = sum(qty for _, qty in bids)
        ask_qty = sum(qty for _, qty in asks)

        best_bid = bids[0][0] if bids else state.candle.close
        best_ask = asks[0][0] if asks else state.candle.close
        mid = (best_bid + best_ask) / 2.0 if (best_bid + best_ask) > 0 else state.candle.close

        imbalance = math.log((bid_qty + 1e-9) / (ask_qty + 1e-9))
        spread = max((best_ask - best_bid) / max(mid, 1e-9), 0.0)
        depth = bid_qty + ask_qty

        body_size = abs(state.candle.close - state.candle.open) / max(state.candle.open, 1e-9)
        total_range = max(state.candle.high - state.candle.low, 0.0)
        wick_ratio = total_range / max(abs(state.candle.close - state.candle.open), 1e-9)

        volume_mean = self._stats["relative_volume"].mean
        relative_volume = (
            state.candle.volume / volume_mean if volume_mean > 1e-12 else 1.0
        )

        return {
            "imbalance": imbalance,
            "spread": spread,
            "depth": depth,
            "body_size": body_size,
            "wick_ratio": wick_ratio,
            "relative_volume": relative_volume,
        }

    @staticmethod
    def _volume_regime_from_z(z_volume: float) -> str:
        if z_volume < -0.35:
            return "LOW"
        if z_volume < 0.35:
            return "MID"
        return "HIGH"

    @staticmethod
    def _spread_regime_from_z(z_spread: float) -> str:
        if z_spread < -0.8:
            return "TIGHT"
        if z_spread < 0.8:
            return "NORM"
        return "WIDE"

    @staticmethod
    def _depth_regime_from_z(z_depth: float) -> str:
        if z_depth < -0.35:
            return "LOW"
        if z_depth < 0.35:
            return "MID"
        return "HIGH"

    @staticmethod
    def _market_regime(volume_regime: str, spread_regime: str) -> str:
        if volume_regime == "HIGH" and spread_regime in {"TIGHT", "NORM"}:
            return "TRENDING"
        if volume_regime == "LOW" and spread_regime == "WIDE":
            return "NOISY"
        return "MIXED"

    def encode_state(self, state: MarketState) -> tuple[str, list[float], dict[str, str]]:
        """Encode state into token + numeric vector + coarse regimes.

        This preserves token behavior and additionally exposes values for
        empirical similar-state memory lookups.
        """
        features = self._extract_features(state)
        candle_dir = self._candle_direction(state.candle.open, state.candle.close)

        z = {
            name: self._stats[name].zscore(value)
            for name, value in features.items()
        }
        token = (
            f"IMB_{self._bucket_generic(z['imbalance'])}_"
            f"SPD_{self._bucket_spread(z['spread'])}_"
            f"DPT_{self._bucket_generic(z['depth'])}_"
            f"BOD_{self._bucket_body(z['body_size'])}_"
            f"WCK_{self._bucket_wick(z['wick_ratio'])}_"
            f"VOL_{self._bucket_generic(z['relative_volume'])}_"
            f"CNDL_{candle_dir}"
        )

        regimes = {
            "volume": self._volume_regime_from_z(z["relative_volume"]),
            "spread": self._spread_regime_from_z(z["spread"]),
            "depth": self._depth_regime_from_z(z["depth"]),
        }
        regimes["market"] = self._market_regime(
            volume_regime=regimes["volume"],
            spread_regime=regimes["spread"],
        )

        vector = [
            float(features["imbalance"]),
            float(features["spread"]),
            float(features["depth"]),
            float(features["body_size"]),
            float(features["wick_ratio"]),
            float(features["relative_volume"]),
        ]

        for name, value in features.items():
            self._stats[name].update(value)

        return token, vector, regimes

    def to_token(self, state: MarketState) -> str:
        token, _, _ = self.encode_state(state)
        return token

    def dump_state(self) -> dict:
        return {
            "stats": {
                name: stats.dump_state()
                for name, stats in self._stats.items()
            }
        }

    @classmethod
    def from_state(cls, state: dict) -> "AdaptiveQuantizer":
        obj = cls()
        stats_state = state.get("stats", {})
        for name in cls._FEATURES:
            if name in stats_state:
                obj._stats[name] = _RollingStats.from_state(stats_state[name])
        return obj


class IncrementalOBLMModel:
    """Incremental SGD classifier for BULL/BEAR probabilities."""

    def __init__(self, n_features: int = 2**13, random_state: int = 42):
        self._n_features = n_features
        self._random_state = random_state
        self._initialized = False

        if _SKLEARN_AVAILABLE:
            self._vectorizer = HashingVectorizer(
                n_features=n_features,
                lowercase=False,
                alternate_sign=False,
                token_pattern=r"[^ ]+",
            )
            self._classifier = SGDClassifier(loss="log_loss", random_state=random_state)
            self._classes = [0, 1]  # 0 -> BEAR, 1 -> BULL
        else:
            # Lightweight online logistic-regression fallback for environments
            # where sklearn isn't installed yet.
            self._weights: dict[int, float] = {}
            self._bias: float = 0.0
            self._learning_rate = 0.08

    @staticmethod
    def _softmax(logits: tuple[float, float]) -> tuple[float, float]:
        max_logit = max(logits)
        exp0 = math.exp(logits[0] - max_logit)
        exp1 = math.exp(logits[1] - max_logit)
        total = exp0 + exp1
        return exp0 / total, exp1 / total

    def predict_bull_probability(self, token: str) -> float:
        if not self._initialized:
            return 0.5

        if _SKLEARN_AVAILABLE:
            x = self._vectorizer.transform([token])
            logit_bull = float(self._classifier.decision_function(x)[0])
        else:
            logit_bull = self._fallback_logit(token)

        _, p_bull = self._softmax((0.0, logit_bull))
        return p_bull

    def predict(self, token: str, minute: datetime) -> PredictionOutput:
        p_bull = self.predict_bull_probability(token)
        direction = "BULL" if p_bull >= 0.5 else "BEAR"
        confidence = p_bull if direction == "BULL" else 1.0 - p_bull
        return PredictionOutput(
            direction=direction,
            probability=float(confidence),
            timestamp=_minute_floor(minute).isoformat(),
        )

    def update(self, token: str, label: str) -> None:
        y = 1 if label == "BULL" else 0

        if _SKLEARN_AVAILABLE:
            x = self._vectorizer.transform([token])
            if not self._initialized:
                self._classifier.partial_fit(x, [y], classes=self._classes)
                self._initialized = True
                return
            self._classifier.partial_fit(x, [y])
            return

        self._fallback_update(token=token, y=y)
        self._initialized = True

    def _fallback_features(self, token: str) -> dict[int, float]:
        parts = token.split("_")
        features: dict[int, float] = {}
        for part in parts:
            idx = hash(part) % self._n_features
            features[idx] = features.get(idx, 0.0) + 1.0
        return features

    def _fallback_logit(self, token: str) -> float:
        logit = self._bias
        for idx, value in self._fallback_features(token).items():
            logit += self._weights.get(idx, 0.0) * value
        return logit

    def _fallback_update(self, token: str, y: int) -> None:
        x = self._fallback_features(token)
        logit = self._bias + sum(self._weights.get(i, 0.0) * v for i, v in x.items())
        p = 1.0 / (1.0 + math.exp(-max(min(logit, 35.0), -35.0)))
        error = y - p

        self._bias += self._learning_rate * error
        for idx, value in x.items():
            self._weights[idx] = self._weights.get(idx, 0.0) + self._learning_rate * error * value

    def dump_state(self) -> dict:
        if _SKLEARN_AVAILABLE:
            classifier = self._classifier if self._initialized else None
            return {
                "sklearn": True,
                "initialized": self._initialized,
                "n_features": self._n_features,
                "random_state": self._random_state,
                "classifier": classifier,
            }

        return {
            "sklearn": False,
            "initialized": self._initialized,
            "n_features": self._n_features,
            "random_state": self._random_state,
            "weights": dict(self._weights),
            "bias": self._bias,
            "learning_rate": self._learning_rate,
        }

    @classmethod
    def from_state(cls, state: dict) -> "IncrementalOBLMModel":
        obj = cls(
            n_features=int(state.get("n_features", 2**13)),
            random_state=int(state.get("random_state", 42)),
        )
        obj._initialized = bool(state.get("initialized", False))

        if state.get("sklearn", False) and _SKLEARN_AVAILABLE:
            classifier = state.get("classifier")
            if classifier is not None:
                obj._classifier = classifier
            return obj

        if not _SKLEARN_AVAILABLE:
            obj._weights = {
                int(k): float(v)
                for k, v in state.get("weights", {}).items()
            }
            obj._bias = float(state.get("bias", 0.0))
            obj._learning_rate = float(state.get("learning_rate", 0.08))
        return obj


class CalibrationTracker:
    """Tracks calibration via Expected Calibration Error (ECE)."""

    def __init__(self, bins: int = 10):
        self._bins = bins
        self._count = [0 for _ in range(bins)]
        self._conf_sum = [0.0 for _ in range(bins)]
        self._acc_sum = [0.0 for _ in range(bins)]

    def update(self, confidence: float, correct: bool) -> None:
        c = min(max(confidence, 0.0), 1.0)
        idx = min(int(c * self._bins), self._bins - 1)
        self._count[idx] += 1
        self._conf_sum[idx] += c
        self._acc_sum[idx] += 1.0 if correct else 0.0

    def expected_calibration_error(self) -> float:
        total = sum(self._count)
        if total == 0:
            return 0.0

        ece = 0.0
        for i in range(self._bins):
            if self._count[i] == 0:
                continue
            avg_conf = self._conf_sum[i] / self._count[i]
            avg_acc = self._acc_sum[i] / self._count[i]
            ece += (self._count[i] / total) * abs(avg_acc - avg_conf)
        return ece

    def summary(self) -> dict[str, float | int]:
        return {
            "samples": sum(self._count),
            "ece": self.expected_calibration_error(),
            "bins": self._bins,
        }

    def dump_state(self) -> dict:
        return {
            "bins": self._bins,
            "count": list(self._count),
            "conf_sum": list(self._conf_sum),
            "acc_sum": list(self._acc_sum),
        }

    @classmethod
    def from_state(cls, state: dict) -> "CalibrationTracker":
        obj = cls(bins=int(state.get("bins", 10)))
        obj._count = [int(v) for v in state.get("count", obj._count)]
        obj._conf_sum = [float(v) for v in state.get("conf_sum", obj._conf_sum)]
        obj._acc_sum = [float(v) for v in state.get("acc_sum", obj._acc_sum)]
        return obj


class ConfidenceWinrateTracker:
    """Track cumulative winrate for confidence thresholds (e.g. >=90, >=80, ...)."""

    def __init__(self, thresholds: list[int] | None = None):
        raw = thresholds or list(range(90, 0, -10))
        cleaned = sorted(
            {
                int(t)
                for t in raw
                if 0 < int(t) <= 100
            },
            reverse=True,
        )
        self._thresholds = cleaned if cleaned else list(range(90, 0, -10))
        self._wins = {threshold: 0 for threshold in self._thresholds}
        self._totals = {threshold: 0 for threshold in self._thresholds}

    @property
    def thresholds(self) -> list[int]:
        return list(self._thresholds)

    def update(self, confidence: float, correct: bool) -> None:
        confidence_pct = min(max(confidence * 100.0, 0.0), 100.0)
        for threshold in self._thresholds:
            if confidence_pct >= threshold:
                self._totals[threshold] += 1
                if correct:
                    self._wins[threshold] += 1

    def summary_rows(self) -> list[dict[str, int | float]]:
        rows: list[dict[str, int | float]] = []
        for threshold in self._thresholds:
            wins = self._wins[threshold]
            total = self._totals[threshold]
            winrate_pct = (wins / total * 100.0) if total > 0 else 0.0
            rows.append(
                {
                    "threshold": threshold,
                    "wins": wins,
                    "total": total,
                    "winrate_pct": winrate_pct,
                }
            )
        return rows


def _log_confidence_winrate_snapshot(
    confidence_logger: logging.Logger,
    tracker: ConfidenceWinrateTracker,
    minute: str,
    source: str,
    confidence_log_path: str,
    confidence_log_max_lines: int,
    empirical_winrate_pct: float | None = None,
) -> None:
    """Write confidence-threshold winrates to dedicated log file."""
    for row in tracker.summary_rows():
        empirical = (
            float(empirical_winrate_pct)
            if empirical_winrate_pct is not None
            else float(row["winrate_pct"])
        )
        confidence_logger.info(
            (
                "WINRATE minute=%s source=%s confidence_gt=%d wins=%d total=%d "
                "winrate=%.2f%% empirical_winrate=%.2f%%"
            ),
            minute,
            source,
            int(row["threshold"]),
            int(row["wins"]),
            int(row["total"]),
            float(row["winrate_pct"]),
            empirical,
        )
    _trim_log_to_last_lines(
        log_path=confidence_log_path,
        max_lines=confidence_log_max_lines,
    )


class OBLMEngine:
    """End-to-end quantize -> predict -> delayed-label update loop."""

    def __init__(
        self,
        quantizer: AdaptiveQuantizer | None = None,
        model: IncrementalOBLMModel | None = None,
        calibration: CalibrationTracker | None = None,
        horizon_minutes: int = 5,
    ):
        self._quantizer = quantizer or AdaptiveQuantizer()
        self._model = model or IncrementalOBLMModel()
        self._calibration = calibration or CalibrationTracker()
        self._horizon = timedelta(minutes=horizon_minutes)
        self._pending: deque[PendingPrediction] = deque()
        self._last_token: str | None = None
        self._last_feature_vector: list[float] = []
        self._last_regimes: dict[str, str] = {}
        self._last_settlements: list[dict[str, object]] = []

    @staticmethod
    def _realized_direction(reference_price: float, current_price: float) -> str:
        return "BULL" if current_price > reference_price else "BEAR"

    def _settle_matured(self, minute: datetime, current_close: float) -> list[dict[str, object]]:
        settled: list[dict[str, object]] = []
        while self._pending and minute >= self._pending[0].minute + self._horizon:
            pending = self._pending.popleft()
            realized = self._realized_direction(
                reference_price=pending.reference_price,
                current_price=current_close,
            )
            logger.info(
                "SETTLE pred_minute=%s ref_close=%.2f eval_close=%.2f realized=%s",
                pending.minute.isoformat(),
                pending.reference_price,
                current_close,
                realized,
            )
            self._model.update(pending.token, realized)
            correct = pending.predicted_direction == realized
            confidence = (
                pending.bull_probability
                if pending.predicted_direction == "BULL"
                else 1.0 - pending.bull_probability
            )
            self._calibration.update(confidence=confidence, correct=correct)
            settled.append(
                {
                    "pred_minute": pending.minute.isoformat(),
                    "reference_price": pending.reference_price,
                    "eval_price": current_close,
                    "predicted": pending.predicted_direction,
                    "realized": realized,
                    "correct": correct,
                    "confidence": confidence,
                }
            )
        return settled

    def process_market_state(self, state: MarketState) -> PredictionOutput:
        minute = _minute_floor(state.timestamp)
        self._last_settlements = self._settle_matured(minute, current_close=state.candle.close)

        token, feature_vector, regimes = self._quantizer.encode_state(state)
        self._last_token = token
        self._last_feature_vector = list(feature_vector)
        self._last_regimes = dict(regimes)
        p_bull = self._model.predict_bull_probability(token)
        prediction = self._model.predict(token, minute=minute)

        self._pending.append(
            PendingPrediction(
                minute=minute,
                token=token,
                reference_price=state.candle.close,
                predicted_direction=prediction.direction,
                bull_probability=p_bull,
            )
        )
        return prediction

    def calibration_summary(self) -> dict[str, float | int]:
        return self._calibration.summary()

    @property
    def last_token(self) -> str | None:
        return self._last_token

    @property
    def pending_count(self) -> int:
        """Return number of predictions waiting for maturity."""
        return len(self._pending)

    @property
    def last_feature_vector(self) -> list[float]:
        return list(self._last_feature_vector)

    @property
    def last_regimes(self) -> dict[str, str]:
        return dict(self._last_regimes)

    @property
    def last_settlements(self) -> list[dict[str, object]]:
        """Return settlement summaries from the latest processing step."""
        return list(self._last_settlements)

    def dump_state(self) -> dict:
        return {
            "horizon_minutes": int(self._horizon.total_seconds() // 60),
            "quantizer": self._quantizer.dump_state(),
            "model": self._model.dump_state(),
            "calibration": self._calibration.dump_state(),
            "pending": [
                {
                    "minute": p.minute.isoformat(),
                    "token": p.token,
                    "reference_price": p.reference_price,
                    "predicted_direction": p.predicted_direction,
                    "bull_probability": p.bull_probability,
                }
                for p in self._pending
            ],
        }

    def save_to_file(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as f:
            pickle.dump(self.dump_state(), f)

    @classmethod
    def load_from_file(cls, path: Path) -> "OBLMEngine":
        with path.open("rb") as f:
            state = pickle.load(f)

        quantizer = AdaptiveQuantizer.from_state(state.get("quantizer", {}))
        model = IncrementalOBLMModel.from_state(state.get("model", {}))
        calibration = CalibrationTracker.from_state(state.get("calibration", {}))
        engine = cls(
            quantizer=quantizer,
            model=model,
            calibration=calibration,
            horizon_minutes=int(state.get("horizon_minutes", 5)),
        )
        for raw in state.get("pending", []):
            engine._pending.append(
                PendingPrediction(
                    minute=datetime.fromisoformat(raw["minute"]),
                    token=str(raw["token"]),
                    reference_price=float(raw["reference_price"]),
                    predicted_direction=str(raw["predicted_direction"]),
                    bull_probability=float(raw["bull_probability"]),
                )
            )
        return engine


async def run_oblm_training(
    symbol: str = "btcusdt",
    model_path: str = "data/oblm/model.pkl",
    save_interval_minutes: int = 1,
    rolling_window: int = 240,
    decision_log_path: str = "logs/oblm/decisions.log",
    decision_log_max_bytes: int = 2_000_000,
    decision_log_backup_count: int = 5,
    decision_log_max_lines: int = 100,
    confidence_log_path: str = "logs/oblm/confidence_winrate.log",
    confidence_log_max_bytes: int = 2_000_000,
    confidence_log_backup_count: int = 5,
    confidence_log_max_lines: int = 10,
    memory_enabled: bool = True,
    memory_sqlite_path: str = "data/oblm/memory.db",
    memory_log_path: str = "logs/oblm/memory_events.log",
    memory_log_max_bytes: int = 2_000_000,
    memory_log_backup_count: int = 5,
    memory_log_max_lines: int = 200,
    memory_k_neighbors: int = 84,
    memory_candidate_limit: int = 2000,
    memory_max_age_days: int = 60,
    memory_bayes_alpha: float = 10.0,
    memory_bayes_beta: float = 10.0,
    memory_min_samples_to_trust: int = 30,
    memory_min_smoothed_winrate: float = 0.55,
) -> None:
    """Run live OBLM training loop and persist only model state.

    Notes:
    - Raw order-book and candle streams are processed in-memory only.
    - Feature quantization is adaptive with a rolling statistics window.
    - Only model checkpoint state is persisted to disk.
    - Decision output is also written to a rolling-window log file.
    """
    decision_logger = _configure_decision_log_file(
        decision_log_path=decision_log_path,
        max_bytes=decision_log_max_bytes,
        backup_count=decision_log_backup_count,
    )
    confidence_logger = _configure_confidence_log_file(
        confidence_log_path=confidence_log_path,
        max_bytes=confidence_log_max_bytes,
        backup_count=confidence_log_backup_count,
    )
    memory_logger = _configure_memory_log_file(
        memory_log_path=memory_log_path,
        max_bytes=memory_log_max_bytes,
        backup_count=memory_log_backup_count,
    )
    confidence_tracker = ConfidenceWinrateTracker()
    latest_memory_empirical_pct: float | None = None
    memory_layer = None
    memory_gate = None
    if memory_enabled:
        MemoryDecisionGateCls, SimilarStateMemoryCls = _load_oblm_memory_components()
        memory_layer = SimilarStateMemoryCls(
            sqlite_path=memory_sqlite_path,
            k_neighbors=memory_k_neighbors,
            candidate_limit=memory_candidate_limit,
            max_age_days=memory_max_age_days,
            bayes_alpha=memory_bayes_alpha,
            bayes_beta=memory_bayes_beta,
        )
        memory_gate = MemoryDecisionGateCls(
            min_samples_to_trust=memory_min_samples_to_trust,
            min_smoothed_winrate=memory_min_smoothed_winrate,
            tradable_volume_regimes=("MID", "HIGH"),
        )
        _log_memory_event(
            memory_logger,
            "startup",
            enabled=True,
            sqlite_path=memory_sqlite_path,
            k_neighbors=memory_k_neighbors,
            bayes_alpha=memory_bayes_alpha,
            bayes_beta=memory_bayes_beta,
            min_samples_to_trust=memory_min_samples_to_trust,
        )
    else:
        _log_memory_event(memory_logger, "startup", enabled=False)
    _log_lifecycle(
        decision_logger,
        "startup",
        symbol=symbol.lower(),
        model_path=model_path,
        save_interval_minutes=max(1, save_interval_minutes),
        rolling_window=rolling_window,
    )
    _trim_log_to_last_lines(
        log_path=decision_log_path,
        max_lines=decision_log_max_lines,
    )

    checkpoint = Path(model_path)
    if checkpoint.exists():
        try:
            engine = OBLMEngine.load_from_file(checkpoint)
            logger.info("Loaded existing OBLM model from %s", checkpoint)
            _log_lifecycle(
                decision_logger,
                "model_load",
                mode="loaded",
                model_exists=True,
                model_size=checkpoint.stat().st_size,
                path=str(checkpoint),
            )
        except ModuleNotFoundError as exc:
            # Common case: checkpoint was saved with sklearn objects but runtime
            # environment doesn't have sklearn installed.
            logger.warning(
                "Checkpoint %s is incompatible in current environment (%s). "
                "Starting with a fresh model.",
                checkpoint,
                exc,
            )
            _log_lifecycle(
                decision_logger,
                "model_load",
                mode="incompatible_checkpoint",
                model_exists=True,
                model_size=checkpoint.stat().st_size,
                path=str(checkpoint),
                error=str(exc),
            )
            engine = OBLMEngine(quantizer=AdaptiveQuantizer(rolling_window=rolling_window))
        except Exception as exc:
            logger.warning(
                "Failed to load checkpoint %s (%s). Starting with a fresh model.",
                checkpoint,
                exc,
            )
            _log_lifecycle(
                decision_logger,
                "model_load",
                mode="load_failed",
                model_exists=True,
                model_size=checkpoint.stat().st_size,
                path=str(checkpoint),
                error=str(exc),
            )
            engine = OBLMEngine(quantizer=AdaptiveQuantizer(rolling_window=rolling_window))
    else:
        engine = OBLMEngine(quantizer=AdaptiveQuantizer(rolling_window=rolling_window))
        logger.info(
            "Initialized new OBLM model (rolling_window=%d)",
            rolling_window,
        )
        _log_lifecycle(
            decision_logger,
            "model_load",
            mode="initialized",
            model_exists=False,
            model_size=0,
            path=str(checkpoint),
        )

    logger.info(
        "Storage policy: raw L2/candle data NOT persisted, only checkpoint file=%s",
        checkpoint,
    )
    logger.info(
        "Decision rolling log enabled: file=%s max_bytes=%d backups=%d",
        decision_log_path,
        decision_log_max_bytes,
        decision_log_backup_count,
    )
    logger.info(
        "Confidence rolling log enabled: file=%s max_bytes=%d backups=%d",
        confidence_log_path,
        confidence_log_max_bytes,
        confidence_log_backup_count,
    )
    confidence_logger.info(
        "CONFIDENCE_TRACKER thresholds=%s",
        ",".join(str(t) for t in confidence_tracker.thresholds),
    )
    _trim_log_to_last_lines(
        log_path=confidence_log_path,
        max_lines=confidence_log_max_lines,
    )
    _trim_log_to_last_lines(
        log_path=memory_log_path,
        max_lines=memory_log_max_lines,
    )

    latest_state: MarketState | None = None

    async def on_market_state(state: MarketState) -> None:
        nonlocal latest_state, latest_memory_empirical_pct
        latest_state = state
        best_bid = state.l2.bids[0][0] if state.l2.bids else float("nan")
        best_ask = state.l2.asks[0][0] if state.l2.asks else float("nan")
        logger.info(
            "SYNC minute=%s bid=%.2f ask=%.2f close=%.2f volume=%.4f",
            state.timestamp.isoformat(),
            best_bid,
            best_ask,
            state.candle.close,
            state.candle.volume,
        )
        output = engine.process_market_state(state)
        memory_payload: dict[str, object] = {
            "memory_winrate": 0.0,
            "smoothed_memory_winrate": 0.5,
            "memory_samples": 0,
            "regime_filtered_samples": 0,
            "match_method": "none",
            "trade_verdict": "SKIP",
        }
        if memory_layer is not None and memory_gate is not None:
            lookup = memory_layer.lookup_similar(
                symbol=symbol,
                token=engine.last_token or "NA",
                feature_vector=engine.last_feature_vector,
                predicted_direction=output.direction,
                regimes=engine.last_regimes,
            )
            volume_regime = engine.last_regimes.get("volume", "MID")
            verdict = memory_gate.evaluate(
                model_confidence=output.probability,
                lookup=lookup,
                volume_regime=volume_regime,
            )
            memory_payload = {
                "memory_winrate": float(lookup.memory_winrate),
                "smoothed_memory_winrate": float(lookup.smoothed_memory_winrate),
                "memory_samples": int(lookup.memory_samples),
                "regime_filtered_samples": int(lookup.regime_filtered_samples),
                "match_method": lookup.match_method,
                "trade_verdict": verdict.verdict,
            }
            latest_memory_empirical_pct = float(lookup.smoothed_memory_winrate) * 100.0
            _log_memory_event(
                memory_logger,
                "lookup",
                minute=output.timestamp,
                direction=output.direction,
                model_confidence=f"{output.probability:.3f}",
                memory_winrate=f"{lookup.memory_winrate:.4f}",
                smoothed_memory_winrate=f"{lookup.smoothed_memory_winrate:.4f}",
                memory_samples=lookup.memory_samples,
                regime_filtered_samples=lookup.regime_filtered_samples,
                match_method=lookup.match_method,
                volume_regime=volume_regime,
                verdict=verdict.verdict,
                verdict_reason=verdict.reason,
            )
            memory_prediction_id = memory_layer.insert_prediction(
                timestamp=output.timestamp,
                symbol=symbol,
                token=engine.last_token or "NA",
                feature_vector=engine.last_feature_vector,
                predicted_direction=output.direction,
                model_confidence=output.probability,
                regimes=engine.last_regimes,
                reference_price=state.candle.close,
                settlement_horizon_minutes=5,
            )
            _log_memory_event(
                memory_logger,
                "insert",
                minute=output.timestamp,
                prediction_id=memory_prediction_id,
                direction=output.direction,
                token=engine.last_token or "NA",
                volume_regime=engine.last_regimes.get("volume", "MID"),
                spread_regime=engine.last_regimes.get("spread", "NORM"),
                depth_regime=engine.last_regimes.get("depth", "MID"),
                market_regime=engine.last_regimes.get("market", "UNKNOWN"),
                model_confidence=f"{output.probability:.3f}",
            )
        has_new_settlement = False
        for settled in engine.last_settlements:
            has_new_settlement = True
            confidence_tracker.update(
                confidence=float(settled["confidence"]),
                correct=bool(settled["correct"]),
            )
            _log_lifecycle(
                decision_logger,
                "settle",
                minute=output.timestamp,
                pred_minute=settled["pred_minute"],
                predicted=settled["predicted"],
                realized=settled["realized"],
                correct=settled["correct"],
                confidence=f"{float(settled['confidence']):.3f}",
                ref_close=f"{float(settled['reference_price']):.2f}",
                eval_close=f"{float(settled['eval_price']):.2f}",
            )
            if memory_layer is not None:
                settled_id = memory_layer.settle_by_prediction_key(
                    symbol=symbol,
                    pred_minute=str(settled["pred_minute"]),
                    predicted_direction=str(settled["predicted"]),
                    settled_at=output.timestamp,
                    realized_direction=str(settled["realized"]),
                    reference_price=float(settled["reference_price"]),
                    eval_price=float(settled["eval_price"]),
                )
                _log_memory_event(
                    memory_logger,
                    "settle",
                    minute=output.timestamp,
                    prediction_id=settled_id or "NA",
                    pred_minute=settled["pred_minute"],
                    predicted=settled["predicted"],
                    realized=settled["realized"],
                    correct=settled["correct"],
                    confidence=f"{float(settled['confidence']):.3f}",
                )
        if has_new_settlement:
            _log_confidence_winrate_snapshot(
                confidence_logger=confidence_logger,
                tracker=confidence_tracker,
                minute=output.timestamp,
                source="settlement",
                confidence_log_path=confidence_log_path,
                confidence_log_max_lines=confidence_log_max_lines,
                empirical_winrate_pct=latest_memory_empirical_pct,
            )
        move = "UP" if output.direction == "BULL" else "DOWN"
        probability_pct = output.probability * 100.0
        logger.info(
            "OBLM %s P=%.3f @ %s",
            output.direction,
            output.probability,
            output.timestamp,
        )
        logger.info(
            "DECISION minute=%s direction=%s probability=%.3f token=%s",
            output.timestamp,
            output.direction,
            output.probability,
            engine.last_token or "NA",
        )
        decision_logger.info(
            (
                "DECISION minute=%s move=%s probability=%.2f%% token=%s "
                "memory_winrate=%.4f memory_smoothed=%.4f memory_samples=%d "
                "match_method=%s verdict=%s"
            ),
            output.timestamp,
            move,
            probability_pct,
            engine.last_token or "NA",
            float(memory_payload["memory_winrate"]),
            float(memory_payload["smoothed_memory_winrate"]),
            int(memory_payload["memory_samples"]),
            str(memory_payload["match_method"]),
            str(memory_payload["trade_verdict"]),
        )
        calibration = engine.calibration_summary()
        model_exists = checkpoint.exists()
        model_size = checkpoint.stat().st_size if model_exists else 0
        decision_logger.info(
            "STATUS minute=%s pending=%d cal_samples=%d cal_ece=%.6f model_exists=%s model_size=%d",
            output.timestamp,
            engine.pending_count,
            int(calibration.get("samples", 0)),
            float(calibration.get("ece", 0.0)),
            model_exists,
            model_size,
        )
        _trim_log_to_last_lines(
            log_path=decision_log_path,
            max_lines=decision_log_max_lines,
        )
        _trim_log_to_last_lines(
            log_path=memory_log_path,
            max_lines=memory_log_max_lines,
        )

    pipeline = BinanceMarketDataPipeline(
        symbol=symbol,
        on_market_state=on_market_state,
        lifecycle_logger=decision_logger,
    )
    stop_event = asyncio.Event()
    _log_lifecycle(
        decision_logger,
        "pipeline_start",
        symbol=symbol.lower(),
    )

    async def periodic_save() -> None:
        while not stop_event.is_set():
            await asyncio.sleep(max(1, save_interval_minutes) * 60)
            engine.save_to_file(checkpoint)
            logger.info("Saved OBLM checkpoint -> %s", checkpoint)
            calibration = engine.calibration_summary()
            now_minute = _minute_floor(datetime.now(timezone.utc)).isoformat()
            model_exists = checkpoint.exists()
            model_size = checkpoint.stat().st_size if model_exists else 0
            _log_lifecycle(
                decision_logger,
                "checkpoint_save",
                minute=now_minute,
                pending=engine.pending_count,
                cal_samples=int(calibration.get("samples", 0)),
                cal_ece=f"{float(calibration.get('ece', 0.0)):.6f}",
                model_exists=model_exists,
                model_size=model_size,
                source="heartbeat",
            )
            decision_logger.info(
                "STATUS minute=%s pending=%d cal_samples=%d cal_ece=%.6f model_exists=%s model_size=%d source=heartbeat",
                now_minute,
                engine.pending_count,
                int(calibration.get("samples", 0)),
                float(calibration.get("ece", 0.0)),
                model_exists,
                model_size,
            )
            _trim_log_to_last_lines(
                log_path=decision_log_path,
                max_lines=decision_log_max_lines,
            )
            _log_confidence_winrate_snapshot(
                confidence_logger=confidence_logger,
                tracker=confidence_tracker,
                minute=now_minute,
                source="heartbeat",
                confidence_log_path=confidence_log_path,
                confidence_log_max_lines=confidence_log_max_lines,
                empirical_winrate_pct=latest_memory_empirical_pct,
            )
            _trim_log_to_last_lines(
                log_path=memory_log_path,
                max_lines=memory_log_max_lines,
            )

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            pass

    saver = asyncio.create_task(periodic_save())
    await pipeline.start()
    logger.info("OBLM training started for symbol=%s", symbol)
    _log_lifecycle(decision_logger, "pipeline_started", symbol=symbol.lower())

    try:
        await stop_event.wait()
    finally:
        _log_lifecycle(decision_logger, "shutdown", stage="begin")
        await pipeline.stop()
        _log_lifecycle(decision_logger, "pipeline_stopped", symbol=symbol.lower())
        saver.cancel()
        try:
            await saver
        except asyncio.CancelledError:
            pass
        # Save final model state only (no raw data persistence).
        engine.save_to_file(checkpoint)
        logger.info("Final OBLM checkpoint saved -> %s", checkpoint)
        model_exists = checkpoint.exists()
        model_size = checkpoint.stat().st_size if model_exists else 0
        _log_lifecycle(
            decision_logger,
            "checkpoint_save",
            minute=_minute_floor(datetime.now(timezone.utc)).isoformat(),
            pending=engine.pending_count,
            model_exists=model_exists,
            model_size=model_size,
            source="shutdown",
        )
        _trim_log_to_last_lines(
            log_path=decision_log_path,
            max_lines=decision_log_max_lines,
        )
        _log_confidence_winrate_snapshot(
            confidence_logger=confidence_logger,
            tracker=confidence_tracker,
            minute=_minute_floor(datetime.now(timezone.utc)).isoformat(),
            source="shutdown",
            confidence_log_path=confidence_log_path,
            confidence_log_max_lines=confidence_log_max_lines,
            empirical_winrate_pct=latest_memory_empirical_pct,
        )
        _trim_log_to_last_lines(
            log_path=memory_log_path,
            max_lines=memory_log_max_lines,
        )
        _log_lifecycle(decision_logger, "shutdown", stage="complete")


class BinanceMarketDataPipeline:
    """Async Binance WebSocket pipeline for L2 depth + 1m candles."""

    def __init__(
        self,
        symbol: str,
        on_market_state: Callable[[MarketState], Awaitable[None]],
        depth_levels: int = 20,
        ws_base_url: str = "wss://stream.binance.com:9443/ws",
        lifecycle_logger: logging.Logger | None = None,
    ):
        self._symbol = symbol.lower()
        self._on_market_state = on_market_state
        self._depth_levels = depth_levels
        self._ws_base = ws_base_url.rstrip("/")
        self._sync = MinuteMarketStateSynchronizer()
        self._running = False
        self._tasks: list[asyncio.Task] = []
        self._lifecycle_logger = lifecycle_logger

    def _depth_url(self) -> str:
        return f"{self._ws_base}/{self._symbol}@depth{self._depth_levels}@1000ms"

    def _kline_url(self) -> str:
        return f"{self._ws_base}/{self._symbol}@kline_1m"

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._tasks = [
            asyncio.create_task(self._depth_loop()),
            asyncio.create_task(self._kline_loop()),
        ]

    async def stop(self) -> None:
        self._running = False
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks = []

    async def _depth_loop(self) -> None:
        await self._consume_loop(self._depth_url(), self._handle_depth_message)

    async def _kline_loop(self) -> None:
        await self._consume_loop(self._kline_url(), self._handle_kline_message)

    async def _consume_loop(
        self,
        url: str,
        handler: Callable[[dict], Awaitable[None]],
    ) -> None:
        if websockets is None:
            raise RuntimeError(
                "websockets package is required for live OBLM training pipeline"
            )
        backoff = 1.0
        stream = "depth" if "@depth" in url else "kline"
        while self._running:
            try:
                if self._lifecycle_logger is not None:
                    _log_lifecycle(
                        self._lifecycle_logger,
                        "ws_connecting",
                        stream=stream,
                        url=url,
                    )
                async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
                    logger.info("Connected to %s", url)
                    if self._lifecycle_logger is not None:
                        _log_lifecycle(
                            self._lifecycle_logger,
                            "ws_connected",
                            stream=stream,
                            url=url,
                        )
                    backoff = 1.0
                    async for payload in ws:
                        if not self._running:
                            break
                        message = json.loads(payload)
                        await handler(message)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("WebSocket loop error (%s): %s", url, exc)
                if self._lifecycle_logger is not None:
                    _log_lifecycle(
                        self._lifecycle_logger,
                        "ws_error",
                        stream=stream,
                        error=type(exc).__name__,
                        backoff_seconds=f"{backoff:.1f}",
                    )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2.0, 30.0)

    async def _handle_depth_message(self, message: dict) -> None:
        raw_bids = message.get("b") or message.get("bids") or []
        raw_asks = message.get("a") or message.get("asks") or []
        bids = [(float(p), float(q)) for p, q in raw_bids][: self._depth_levels]
        asks = [(float(p), float(q)) for p, q in raw_asks][: self._depth_levels]

        event_ms = int(message.get("E", 0))
        if event_ms > 0:
            depth_ts = _utc_from_ms(event_ms)
        else:
            # Partial book-depth stream payloads may not include event time.
            depth_ts = datetime.now(timezone.utc)

        state = self._sync.add_l2(
            L2Snapshot(timestamp=depth_ts, bids=bids, asks=asks)
        )
        if state is not None:
            await self._on_market_state(state)

    async def _handle_kline_message(self, message: dict) -> None:
        kline = message.get("k", {})
        if not kline:
            return
        close_ms = int(kline.get("T", 0))
        if close_ms <= 0:
            return

        candle = Candle1m(
            timestamp=_utc_from_ms(close_ms),
            open=float(kline.get("o", 0.0)),
            high=float(kline.get("h", 0.0)),
            low=float(kline.get("l", 0.0)),
            close=float(kline.get("c", 0.0)),
            volume=float(kline.get("v", 0.0)),
        )
        state = self._sync.add_candle(candle)
        if state is not None:
            await self._on_market_state(state)


def _parse_oblm_args() -> argparse.Namespace:
    """Parse command-line args for OBLM training runner."""
    parser = argparse.ArgumentParser(
        description="Run OBLM live training loop",
    )
    parser.add_argument("--symbol", default="btcusdt", help="Binance symbol")
    parser.add_argument(
        "--model-path",
        default="data/oblm/model.pkl",
        help="Path to OBLM checkpoint file",
    )
    parser.add_argument(
        "--save-interval-minutes",
        type=int,
        default=1,
        help="Checkpoint save interval in minutes",
    )
    parser.add_argument(
        "--rolling-window",
        type=int,
        default=240,
        help="Rolling window size for adaptive quantizer",
    )
    parser.add_argument(
        "--decision-log-path",
        default="logs/oblm/decisions.log",
        help="Decision/lifecycle log file path",
    )
    parser.add_argument(
        "--decision-log-max-bytes",
        type=int,
        default=2_000_000,
        help="Decision log max file size before rotation",
    )
    parser.add_argument(
        "--decision-log-backup-count",
        type=int,
        default=5,
        help="Number of rotated decision log backups",
    )
    parser.add_argument(
        "--decision-log-max-lines",
        type=int,
        default=100,
        help="Keep only the latest N lines in decision log",
    )
    parser.add_argument(
        "--confidence-log-path",
        default="logs/oblm/confidence_winrate.log",
        help="Confidence winrate log file path",
    )
    parser.add_argument(
        "--confidence-log-max-bytes",
        type=int,
        default=2_000_000,
        help="Confidence log max file size before rotation",
    )
    parser.add_argument(
        "--confidence-log-backup-count",
        type=int,
        default=5,
        help="Number of rotated confidence log backups",
    )
    parser.add_argument(
        "--confidence-log-max-lines",
        type=int,
        default=10,
        help="Keep only the latest N lines in confidence log",
    )
    parser.add_argument(
        "--memory-enabled",
        action="store_true",
        help="Enable similar-state empirical memory layer",
    )
    parser.add_argument(
        "--memory-disabled",
        action="store_true",
        help="Disable similar-state empirical memory layer",
    )
    parser.add_argument(
        "--memory-sqlite-path",
        default="data/oblm/memory.db",
        help="SQLite path for similar-state memory store",
    )
    parser.add_argument(
        "--memory-log-path",
        default="logs/oblm/memory_events.log",
        help="Similar-state memory event log path",
    )
    parser.add_argument(
        "--memory-k-neighbors",
        type=int,
        default=84,
        help="K for vector nearest-neighbor similarity lookup",
    )
    parser.add_argument(
        "--memory-candidate-limit",
        type=int,
        default=2000,
        help="Candidate settled rows to scan before selecting top-k neighbors",
    )
    parser.add_argument(
        "--memory-max-age-days",
        type=int,
        default=60,
        help="Only use memory records newer than this age in days",
    )
    parser.add_argument(
        "--memory-bayes-alpha",
        type=float,
        default=10.0,
        help="Bayesian prior alpha for smoothed empirical winrate",
    )
    parser.add_argument(
        "--memory-bayes-beta",
        type=float,
        default=10.0,
        help="Bayesian prior beta for smoothed empirical winrate",
    )
    parser.add_argument(
        "--memory-min-samples-to-trust",
        type=int,
        default=30,
        help="Minimum memory sample count required by decision gate",
    )
    parser.add_argument(
        "--memory-min-smoothed-winrate",
        type=float,
        default=0.55,
        help="Minimum smoothed empirical winrate required by decision gate",
    )
    return parser.parse_args()


def _setup_default_logging() -> None:
    """Configure default console logging for CLI usage."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def main() -> None:
    """CLI entry point for OBLM training."""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    _setup_default_logging()
    args = _parse_oblm_args()
    memory_enabled = True
    if args.memory_disabled:
        memory_enabled = False
    elif args.memory_enabled:
        memory_enabled = True
    asyncio.run(
        run_oblm_training(
            symbol=args.symbol,
            model_path=args.model_path,
            save_interval_minutes=args.save_interval_minutes,
            rolling_window=args.rolling_window,
            decision_log_path=args.decision_log_path,
            decision_log_max_bytes=args.decision_log_max_bytes,
            decision_log_backup_count=args.decision_log_backup_count,
            decision_log_max_lines=args.decision_log_max_lines,
            confidence_log_path=args.confidence_log_path,
            confidence_log_max_bytes=args.confidence_log_max_bytes,
            confidence_log_backup_count=args.confidence_log_backup_count,
            confidence_log_max_lines=args.confidence_log_max_lines,
            memory_enabled=memory_enabled,
            memory_sqlite_path=args.memory_sqlite_path,
            memory_log_path=args.memory_log_path,
            memory_k_neighbors=args.memory_k_neighbors,
            memory_candidate_limit=args.memory_candidate_limit,
            memory_max_age_days=args.memory_max_age_days,
            memory_bayes_alpha=args.memory_bayes_alpha,
            memory_bayes_beta=args.memory_bayes_beta,
            memory_min_samples_to_trust=args.memory_min_samples_to_trust,
            memory_min_smoothed_winrate=args.memory_min_smoothed_winrate,
        )
    )


if __name__ == "__main__":
    main()
