"""OBLM v2: Symbolic strategy with fixed-time settlement and sequence analytics.

This module implements the symbolic strategy described in the implementation guide:
- 1m synchronized L2 + candle ingestion
- Adaptive symbolic tokenization including VOL2H
- Online directional model
- Fixed-time settlement (default 5 minutes)
- Calibration + confidence winrate tracking
- 25-candle sequence analytics:
  - Position-aware win/loss table
  - Fuzzy gradient table
  - N-gram pattern discovery
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
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
    try:
        from sklearn.cluster import HDBSCAN as SklearnHDBSCAN
        _SKLEARN_HDBSCAN_AVAILABLE = True
    except Exception:  # pragma: no cover
        SklearnHDBSCAN = None  # type: ignore[assignment]
        _SKLEARN_HDBSCAN_AVAILABLE = False

    _SKLEARN_AVAILABLE = True
except ImportError:  # pragma: no cover
    HashingVectorizer = None  # type: ignore[assignment]
    SGDClassifier = None  # type: ignore[assignment]
    SklearnHDBSCAN = None  # type: ignore[assignment]
    _SKLEARN_HDBSCAN_AVAILABLE = False
    _SKLEARN_AVAILABLE = False

logger = logging.getLogger(__name__)
MODEL_FEATURE_REGIME = "syllable_v1"


def _configure_decision_log_file(
    decision_log_path: str,
    max_bytes: int,
    backup_count: int,
) -> logging.Logger:
    decision_logger = logging.getLogger(f"{__name__}.decision")
    decision_logger.setLevel(logging.INFO)
    decision_logger.propagate = False

    log_path = Path(decision_log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.touch(exist_ok=True)
    resolved = str(log_path.resolve())

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


def _configure_symbolic_summary_log_file(
    summary_log_path: str,
    max_bytes: int,
    backup_count: int,
) -> logging.Logger:
    summary_logger = logging.getLogger(f"{__name__}.symbolic_summary")
    summary_logger.setLevel(logging.INFO)
    summary_logger.propagate = False

    log_path = Path(summary_log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.touch(exist_ok=True)
    resolved = str(log_path.resolve())

    for handler in summary_logger.handlers:
        if isinstance(handler, RotatingFileHandler):
            if Path(handler.baseFilename).resolve() == log_path.resolve():
                return summary_logger

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
    summary_logger.addHandler(file_handler)
    return summary_logger


def _trim_log_to_last_lines(log_path: str, max_lines: int) -> None:
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


def _parse_timestamp_like(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        raw = float(value)
        # Heuristic: values larger than ~year 2286 in seconds are very likely milliseconds.
        if raw > 10_000_000_000:
            raw = raw / 1000.0
        return datetime.fromtimestamp(raw, tz=timezone.utc)

    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        return _parse_timestamp_like(int(text))
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _load_prefill_candles(path: str, limit: int = 10080) -> list["Candle1m"]:
    """Load 1m candles from common Freqtrade exports (JSON/CSV)."""

    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(f"Prefill candles file not found: {source}")

    def _from_row(row: dict[str, object]) -> Candle1m | None:
        ts = _parse_timestamp_like(
            row.get("timestamp")
            or row.get("date")
            or row.get("datetime")
            or row.get("time")
            or row.get("t")
        )
        if ts is None:
            return None
        try:
            return Candle1m(
                timestamp=ts,
                open=float(row.get("open") or row.get("o") or 0.0),
                high=float(row.get("high") or row.get("h") or 0.0),
                low=float(row.get("low") or row.get("l") or 0.0),
                close=float(row.get("close") or row.get("c") or 0.0),
                volume=float(row.get("volume") or row.get("v") or 0.0),
            )
        except (TypeError, ValueError):
            return None

    candles: list[Candle1m] = []
    suffix = source.suffix.lower()
    if suffix == ".csv":
        with source.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for raw in reader:
                item = _from_row({k.lower(): v for k, v in raw.items()})
                if item is not None:
                    candles.append(item)
    else:
        # JSON variants supported:
        # - [[ts, open, high, low, close, volume], ...]
        # - [{timestamp/open/high/low/close/volume}, ...]
        # - {"data": [...]} / {"candles": [...]} / {"ohlcv": [...]} / {"rows": [...]}.
        with source.open("r", encoding="utf-8") as f:
            payload = json.load(f)
        if isinstance(payload, dict):
            for key in ("data", "candles", "ohlcv", "rows"):
                if key in payload:
                    payload = payload[key]
                    break
        if not isinstance(payload, list):
            raise ValueError("Unsupported prefill format: expected list-like candle payload")

        for entry in payload:
            if isinstance(entry, dict):
                item = _from_row({str(k).lower(): v for k, v in entry.items()})
                if item is not None:
                    candles.append(item)
                continue
            if isinstance(entry, list | tuple) and len(entry) >= 6:
                ts = _parse_timestamp_like(entry[0])
                if ts is None:
                    continue
                try:
                    candles.append(
                        Candle1m(
                            timestamp=ts,
                            open=float(entry[1]),
                            high=float(entry[2]),
                            low=float(entry[3]),
                            close=float(entry[4]),
                            volume=float(entry[5]),
                        )
                    )
                except (TypeError, ValueError):
                    continue

    candles.sort(key=lambda c: c.timestamp)
    keep = max(1, int(limit))
    return candles[-keep:]


def _utc_from_ms(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def _minute_floor(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.replace(second=0, microsecond=0)


def _is_trading_session_open(
    minute: datetime,
    enabled: bool,
    weekdays_only: bool,
    start_hour_utc: int,
    end_hour_utc: int,
) -> bool:
    """Return True when trading-session gate allows this minute.

    When disabled, trading is allowed 24/7.
    When enabled, a UTC hour window and optional weekday filter are applied.
    """
    if not enabled:
        return True

    ts = minute if minute.tzinfo is not None else minute.replace(tzinfo=timezone.utc)
    if weekdays_only and ts.weekday() >= 5:
        return False

    start = int(start_hour_utc) % 24
    end = int(end_hour_utc) % 24
    if start == end:
        return True
    if start < end:
        return start <= ts.hour < end
    return ts.hour >= start or ts.hour < end


def _opposite_direction(direction: str) -> str:
    return "BEAR" if direction == "BULL" else "BULL"


def _position_direction_label(direction: str) -> str:
    return "LONG" if direction == "BULL" else "SHORT"


def _format_position_label(position_1_based: int, sequence_len: int = 25) -> str:
    idx0 = max(0, int(position_1_based) - 1)
    if idx0 == 0:
        return f"{idx0} (Start)"
    if idx0 == (sequence_len // 2):
        return f"{idx0} (Mid)"
    if idx0 >= (sequence_len - 1):
        return f"{idx0} (Last)"
    return str(idx0)


def _gradient_strength_label(delta: float) -> str:
    abs_delta = abs(delta)
    if abs_delta < 0.15:
        return "Neutral/Noise"
    if delta > 0:
        return "Strong Bullish" if abs_delta >= 0.25 else "Bullish"
    return "Strong Bearish" if abs_delta >= 0.25 else "Bearish"


def _parse_symbolic_token(token: str) -> dict[str, str]:
    parts = token.split("_")
    parsed: dict[str, str] = {}
    for i in range(0, len(parts) - 1, 2):
        parsed[parts[i]] = parts[i + 1]
    return parsed


def _token_fragments(token: str) -> list[str]:
    parsed = _parse_symbolic_token(token)
    return [f"{feature}_{label}" for feature, label in parsed.items()]


def _build_syllable_model_input(token: str, include_interactions: bool = True) -> str:
    parsed = _parse_symbolic_token(token)
    fragments = [f"{k}_{v}" for k, v in parsed.items()]
    if include_interactions:
        pair_keys = [
            ("IMB", "RGF"),
            ("VOL2H", "CNDL"),
            ("BOD", "WCK"),
            ("RGM", "CNDL"),
            ("SPD", "DPT"),
        ]
        for left, right in pair_keys:
            lv = parsed.get(left)
            rv = parsed.get(right)
            if lv is None or rv is None:
                continue
            fragments.append(f"{left}_{lv}+{right}_{rv}")
    return " ".join(fragments)


@dataclass
class L2Snapshot:
    timestamp: datetime
    bids: list[tuple[float, float]]
    asks: list[tuple[float, float]]


@dataclass
class Candle1m:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class MarketState:
    timestamp: datetime
    l2: L2Snapshot
    candle: Candle1m


@dataclass
class PredictionOutput:
    direction: str
    probability: float
    timestamp: str
    action: str = "TRADE"
    uncertainty: float = 0.0
    reason: str = "ok"


@dataclass
class PendingPrediction:
    minute: datetime
    token: str
    model_input: str
    reference_price: float
    predicted_direction: str
    bull_probability: float


class MinuteMarketStateSynchronizer:
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
        self._window = max(5, int(window))
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
        return {"window": self._window, "values": list(self._values)}

    @classmethod
    def from_state(cls, state: dict) -> "_RollingStats":
        obj = cls(window=int(state.get("window", 240)))
        for value in state.get("values", []):
            obj.update(float(value))
        return obj


class RollingIndicatorState:
    """Trend + volume context with 7d defaults."""

    def __init__(self, rolling_window: int = 10080):
        self._rolling_window = max(120, int(rolling_window))
        self._volumes_7d: deque[float] = deque(maxlen=self._rolling_window)
        self._volumes_2h: deque[float] = deque(maxlen=120)
        self._ret_1m_stats = _RollingStats(self._rolling_window)
        self._range_1m_stats = _RollingStats(self._rolling_window)

    def update(self, candle: Candle1m) -> dict[str, float | None]:
        ret_1m = (candle.close - candle.open) / max(abs(candle.open), 1e-9)
        range_1m = (candle.high - candle.low) / max(abs(candle.open), 1e-9)

        self._volumes_7d.append(float(candle.volume))
        self._volumes_2h.append(float(candle.volume))
        self._ret_1m_stats.update(ret_1m)
        self._range_1m_stats.update(range_1m)

        avg_volume_1m_7d: float | None = None
        if len(self._volumes_7d) >= self._rolling_window:
            avg_volume_1m_7d = sum(self._volumes_7d) / len(self._volumes_7d)

        if avg_volume_1m_7d and len(self._volumes_2h) == 120 and avg_volume_1m_7d > 1e-12:
            volume_2h = sum(self._volumes_2h)
            baseline_2h = avg_volume_1m_7d * 120.0
            volume_2h_vs_avg = volume_2h / baseline_2h
        else:
            volume_2h_vs_avg = 1.0

        return {
            "avg_volume_1m_7d": avg_volume_1m_7d,
            "volume_2h_vs_avg": volume_2h_vs_avg,
            "rgm": self._ret_1m_stats.zscore(ret_1m),
            "rgf": self._range_1m_stats.zscore(range_1m),
        }

    def dump_state(self) -> dict:
        return {
            "rolling_window": self._rolling_window,
            "volumes_7d": list(self._volumes_7d),
            "volumes_2h": list(self._volumes_2h),
            "ret_1m_stats": self._ret_1m_stats.dump_state(),
            "range_1m_stats": self._range_1m_stats.dump_state(),
        }

    @classmethod
    def from_state(cls, state: dict) -> "RollingIndicatorState":
        obj = cls(rolling_window=int(state.get("rolling_window", 10080)))
        obj._volumes_7d = deque(
            (float(v) for v in state.get("volumes_7d", [])),
            maxlen=obj._rolling_window,
        )
        obj._volumes_2h = deque(
            (float(v) for v in state.get("volumes_2h", [])),
            maxlen=120,
        )
        obj._ret_1m_stats = _RollingStats.from_state(state.get("ret_1m_stats", {}))
        obj._range_1m_stats = _RollingStats.from_state(state.get("range_1m_stats", {}))
        return obj


class AdaptiveQuantizer:
    _FEATURES = (
        "imbalance",
        "spread",
        "depth",
        "body_size",
        "wick_ratio",
        "relative_volume",
        "volume_2h_vs_avg",
        "rgm",
        "rgf",
    )

    def __init__(self, rolling_window: int = 10080):
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

    def _extract_features(
        self,
        state: MarketState,
        indicator_context: dict[str, float | None],
    ) -> dict[str, float]:
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
        body_size = abs(state.candle.close - state.candle.open) / max(abs(state.candle.open), 1e-9)
        total_range = max(state.candle.high - state.candle.low, 0.0)
        wick_ratio = total_range / max(abs(state.candle.close - state.candle.open), 1e-9)

        avg_volume_1m_7d = indicator_context.get("avg_volume_1m_7d")
        if avg_volume_1m_7d and float(avg_volume_1m_7d) > 1e-12:
            relative_volume = state.candle.volume / float(avg_volume_1m_7d)
        else:
            relative_volume = 1.0

        return {
            "imbalance": imbalance,
            "spread": spread,
            "depth": depth,
            "body_size": body_size,
            "wick_ratio": wick_ratio,
            "relative_volume": relative_volume,
            "volume_2h_vs_avg": float(indicator_context.get("volume_2h_vs_avg", 1.0) or 1.0),
            "rgm": float(indicator_context.get("rgm", 0.0) or 0.0),
            "rgf": float(indicator_context.get("rgf", 0.0) or 0.0),
        }

    def to_token(self, state: MarketState, indicator_context: dict[str, float | None]) -> str:
        features = self._extract_features(state=state, indicator_context=indicator_context)
        candle_dir = self._candle_direction(state.candle.open, state.candle.close)
        z = {name: self._stats[name].zscore(value) for name, value in features.items()}

        token = (
            f"IMB_{self._bucket_generic(z['imbalance'])}_"
            f"SPD_{self._bucket_spread(z['spread'])}_"
            f"DPT_{self._bucket_generic(z['depth'])}_"
            f"BOD_{self._bucket_body(z['body_size'])}_"
            f"WCK_{self._bucket_wick(z['wick_ratio'])}_"
            f"VOL_{self._bucket_generic(z['relative_volume'])}_"
            f"VOL2H_{self._bucket_generic(z['volume_2h_vs_avg'])}_"
            f"RGM_{self._bucket_generic(z['rgm'])}_"
            f"RGF_{self._bucket_generic(z['rgf'])}_"
            f"CNDL_{candle_dir}"
        )

        for name, value in features.items():
            self._stats[name].update(value)
        return token

    def dump_state(self) -> dict:
        return {"stats": {name: stats.dump_state() for name, stats in self._stats.items()}}

    @classmethod
    def from_state(cls, state: dict) -> "AdaptiveQuantizer":
        obj = cls()
        stats_state = state.get("stats", {})
        for name in cls._FEATURES:
            if name in stats_state:
                obj._stats[name] = _RollingStats.from_state(stats_state[name])
        return obj


class IncrementalOBLMModel:
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
            self._classes = [0, 1]
        else:
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
            try:
                x = self._vectorizer.transform([token])
                logit_bull = float(self._classifier.decision_function(x)[0])
            except Exception:
                # Fallback safely if checkpoint had an unfitted classifier.
                self._initialized = False
                return 0.5
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
        parts = token.split()
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
            else:
                obj._initialized = False
            return obj

        if not _SKLEARN_AVAILABLE:
            obj._weights = {int(k): float(v) for k, v in state.get("weights", {}).items()}
            obj._bias = float(state.get("bias", 0.0))
            obj._learning_rate = float(state.get("learning_rate", 0.08))
        return obj


class CalibrationTracker:
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
        return {"samples": sum(self._count), "ece": self.expected_calibration_error(), "bins": self._bins}

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
    def __init__(self, thresholds: list[int] | None = None, rolling_window: int = 10):
        raw = thresholds or list(range(90, 0, -10))
        cleaned = sorted({int(t) for t in raw if 0 < int(t) <= 100}, reverse=True)
        self._thresholds = cleaned if cleaned else list(range(90, 0, -10))
        self._vol2h_buckets = ["VLOW", "LOW", "MID", "HIGH", "VHIGH", "NA"]
        self._rolling_window = max(1, int(rolling_window))
        self._recent: deque[tuple[float, bool, str]] = deque(maxlen=self._rolling_window)

    @property
    def thresholds(self) -> list[int]:
        return list(self._thresholds)

    def update(self, confidence: float, correct: bool, vol2h_bucket: str | None = None) -> None:
        bucket = str(vol2h_bucket or "NA").upper()
        if bucket not in self._vol2h_buckets:
            bucket = "NA"
        self._recent.append((float(confidence), bool(correct), bucket))

    def summary_rows(self) -> list[dict[str, int | float]]:
        rows: list[dict[str, int | float]] = []
        for threshold in self._thresholds:
            wins = 0
            total = 0
            for conf, correct, _bucket in self._recent:
                if conf * 100.0 >= threshold:
                    total += 1
                    if correct:
                        wins += 1
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

    def summary_rows_vol2h_by_threshold(self) -> list[dict[str, int | float | str]]:
        rows: list[dict[str, int | float | str]] = []
        for bucket in self._vol2h_buckets:
            for threshold in self._thresholds:
                wins = 0
                total = 0
                for conf, correct, rec_bucket in self._recent:
                    if rec_bucket != bucket:
                        continue
                    if conf * 100.0 >= threshold:
                        total += 1
                        if correct:
                            wins += 1
                winrate_pct = (wins / total * 100.0) if total > 0 else 0.0
                rows.append(
                    {
                        "bucket": bucket,
                        "threshold": threshold,
                        "wins": wins,
                        "total": total,
                        "winrate_pct": winrate_pct,
                    }
                )
        return rows


class SymbolicPatternTracker:
    """Tracks positional, fuzzy-gradient and n-gram sequence patterns."""

    def __init__(
        self,
        sequence_len: int = 25,
        ngram_size: int = 3,
        cluster_mode: str = "tree",
        rarity_z_threshold: float = 2.5,
        impact_weight_cap: float = 10.0,
        distance_threshold: float = 9.0,
        min_cluster_samples: int = 30,
        edge_winrate_threshold: float = 0.60,
        purity_split_winrate_threshold: float = 0.75,
        purity_split_min_support: int = 30,
        purity_split_tighten_factor: float = 0.60,
        purity_split_min_outliers: int = 1,
        tree_rebuild_interval: int = 25,
        tree_min_leaf_samples: int = 20,
        tree_max_depth: int = 4,
        tree_min_gain: float = 0.005,
        tree_history_cap: int = 5000,
        hdbscan_min_cluster_size: int = 20,
        hdbscan_min_samples: int = 10,
        hdbscan_rebuild_interval: int = 25,
        hdbscan_outcome_weight: float = 2.0,
        hdbscan_embedding_dim: int = 256,
    ):
        self.sequence_len = max(2, int(sequence_len))
        self.ngram_size = max(2, int(ngram_size))
        requested_mode = str(cluster_mode or "tree").strip().lower()
        if requested_mode not in {"tree", "hdbscan"}:
            requested_mode = "tree"
        self.cluster_mode_requested = requested_mode
        self.cluster_mode_active = requested_mode
        if self.cluster_mode_requested == "hdbscan" and not _SKLEARN_HDBSCAN_AVAILABLE:
            self.cluster_mode_active = "tree"
            logger.warning("HDBSCAN clustering requested but unavailable; falling back to tree mode.")
        self.rarity_z_threshold = max(0.1, float(rarity_z_threshold))
        self.impact_weight_cap = max(1.0, float(impact_weight_cap))
        self.distance_threshold = max(0.1, float(distance_threshold))
        self.min_cluster_samples = max(1, int(min_cluster_samples))
        self.edge_winrate_threshold = min(max(float(edge_winrate_threshold), 0.50), 0.99)
        self.purity_split_winrate_threshold = min(
            max(float(purity_split_winrate_threshold), 0.50),
            0.99,
        )
        self.purity_split_min_support = max(1, int(purity_split_min_support))
        self.purity_split_tighten_factor = min(
            max(float(purity_split_tighten_factor), 0.10),
            1.0,
        )
        self.purity_split_min_outliers = max(1, int(purity_split_min_outliers))
        self.tree_rebuild_interval = max(1, int(tree_rebuild_interval))
        self.tree_min_leaf_samples = max(2, int(tree_min_leaf_samples))
        self.tree_max_depth = max(1, int(tree_max_depth))
        self.tree_min_gain = max(0.0, float(tree_min_gain))
        self.tree_history_cap = max(100, int(tree_history_cap))
        self.hdbscan_min_cluster_size = max(2, int(hdbscan_min_cluster_size))
        self.hdbscan_min_samples = max(1, int(hdbscan_min_samples))
        self.hdbscan_rebuild_interval = max(1, int(hdbscan_rebuild_interval))
        self.hdbscan_outcome_weight = max(0.0, float(hdbscan_outcome_weight))
        self.hdbscan_embedding_dim = max(32, int(hdbscan_embedding_dim))
        self._rolling_tokens: deque[str] = deque(maxlen=self.sequence_len)
        self._snapshot_by_minute: dict[str, dict[str, object]] = {}

        self._position_stats: dict[tuple[int, str, str], tuple[int, int]] = {}
        self._fragment_stats: dict[str, tuple[int, int]] = {}
        self._ngram_stats: dict[str, tuple[int, int]] = {}

        self._token_position_counts: dict[tuple[int, str], int] = {}
        self._position_total_sequences: dict[int, int] = {}
        self._clusters: dict[int, dict[str, object]] = {}
        self._next_cluster_id = 1
        self._settled_sequences_by_direction: dict[str, list[dict[str, object]]] = {
            "BULL": [],
            "BEAR": [],
        }
        self._tree_by_direction: dict[str, dict[str, object]] = {}
        self._hdbscan_clusters_by_direction: dict[str, dict[int, dict[str, object]]] = {}
        self._next_tree_node_id = 1
        self._last_cluster_signal: dict[str, object] = {
            "cluster_id": None,
            "direction": "NA",
            "distance": None,
            "support": 0,
            "winrate_pct": 0.0,
            "qualified": False,
            "source": "cluster",
        }

        self._win_sequences = 0
        self._loss_sequences = 0
        self._partial_sequences = 0
        self._full_sequences = 0

    @staticmethod
    def _parse_token(token: str) -> dict[str, str]:
        parts = token.split("_")
        parsed: dict[str, str] = {}
        for i in range(0, len(parts) - 1, 2):
            parsed[parts[i]] = parts[i + 1]
        return parsed

    @classmethod
    def _token_fragments(cls, token: str) -> set[str]:
        parsed = cls._parse_token(token)
        return {f"{feature}_{label}" for feature, label in parsed.items()}

    @classmethod
    def _token_signature(cls, token: str) -> str:
        parsed = cls._parse_token(token)
        wanted = ["IMB", "VOL", "VOL2H", "RGF", "CNDL"]
        return "|".join(f"{k}:{parsed.get(k, 'NA')}" for k in wanted)

    @staticmethod
    def _commonality_from_winrate(winrate_pct: float) -> str:
        if winrate_pct >= 60.0:
            return "High in Wins"
        if winrate_pct <= 40.0:
            return "High in Losses"
        return "Random/No correlation"

    def observe_token(self, token: str) -> None:
        self._rolling_tokens.append(token)

    def snapshot_prediction(self, minute: datetime, predicted_direction: str | None = None) -> None:
        if len(self._rolling_tokens) > 0:
            self._snapshot_by_minute[_minute_floor(minute).isoformat()] = {
                "seq": list(self._rolling_tokens),
                "predicted_direction": str(predicted_direction or "BULL"),
            }

    def record_prediction(self, minute: datetime, token: str, predicted_direction: str | None = None) -> None:
        # Backward-compatible helper: observe token + snapshot prediction context.
        self.observe_token(token)
        self.snapshot_prediction(minute, predicted_direction=predicted_direction)

    def bootstrap_status(self) -> dict[str, int]:
        collected = len(self._rolling_tokens)
        needed = self.sequence_len
        remaining = max(0, needed - collected)
        return {
            "collected": collected,
            "needed": needed,
            "remaining": remaining,
            "snapshots_waiting_settle": len(self._snapshot_by_minute),
        }

    def settle_prediction(self, minute: datetime, is_win: bool) -> dict[str, list[dict[str, object]]]:
        key = _minute_floor(minute).isoformat()
        snapshot = self._snapshot_by_minute.pop(key, None)
        if not snapshot:
            return {
                "winloss_rows": [],
                "gradient_rows": [],
                "ngram_rows": [],
                "sequence_mode": "missing",
                "sequence_len": 0,
                "cluster": {
                    "cluster_id": None,
                    "direction": "NA",
                    "distance": None,
                    "support": 0,
                    "winrate_pct": 0.0,
                    "qualified": False,
                },
            }

        seq = [str(x) for x in snapshot.get("seq", [])]
        predicted_direction = str(snapshot.get("predicted_direction", "BULL"))

        sequence_mode = "full" if len(seq) >= self.sequence_len else "partial"
        if sequence_mode == "full":
            self._full_sequences += 1
        else:
            self._partial_sequences += 1

        if is_win:
            self._win_sequences += 1
        else:
            self._loss_sequences += 1

        for idx, token in enumerate(seq):
            for fragment in self._token_fragments(token):
                feature, label = fragment.split("_", 1)
                stat_key = (idx + 1, feature, label)
                wins, total = self._position_stats.get(stat_key, (0, 0))
                wins += 1 if is_win else 0
                total += 1
                self._position_stats[stat_key] = (wins, total)

        unique_fragments = set()
        for token in seq:
            unique_fragments.update(self._token_fragments(token))
        for fragment in unique_fragments:
            wins, losses = self._fragment_stats.get(fragment, (0, 0))
            if is_win:
                wins += 1
            else:
                losses += 1
            self._fragment_stats[fragment] = (wins, losses)

        signatures = [self._token_signature(t) for t in seq]
        unique_ngrams = set()
        for i in range(0, len(signatures) - self.ngram_size + 1):
            pattern = " -> ".join(signatures[i : i + self.ngram_size])
            unique_ngrams.add(pattern)
        for pattern in unique_ngrams:
            wins, losses = self._ngram_stats.get(pattern, (0, 0))
            if is_win:
                wins += 1
            else:
                losses += 1
            self._ngram_stats[pattern] = (wins, losses)

        cluster_result: dict[str, object] = {
            "cluster_id": None,
            "direction": _position_direction_label(predicted_direction),
            "distance": None,
            "support": 0,
            "winrate_pct": 0.0,
            "qualified": False,
            "source": "cluster",
        }
        if sequence_mode == "full":
            self._update_token_position_counts(seq)
            self._record_settled_sequence(
                seq=seq,
                predicted_direction=predicted_direction,
                is_win=bool(is_win),
            )
            cluster_result = self._assign_and_update_cluster(
                seq=seq,
                predicted_direction=predicted_direction,
                is_win=is_win,
            )
            tree_view = self._tree_signal_from_current_window(
                seq=seq,
                predicted_direction=predicted_direction,
            )
            if tree_view is not None:
                cluster_result["tree_leaf_id"] = str(tree_view.get("cluster_id", "NA"))
                cluster_result["tree_path"] = str(tree_view.get("tree_path", "root"))
                cluster_result["tree_winrate_pct"] = float(tree_view.get("winrate_pct", 0.0))
                cluster_result["tree_support"] = int(tree_view.get("support", 0))

        return {
            "winloss_rows": self.winloss_rows(limit=40),
            "gradient_rows": self.gradient_rows(limit=40),
            "ngram_rows": self.ngram_rows(limit=40),
            "sequence_mode": sequence_mode,
            "sequence_len": len(seq),
            "cluster": cluster_result,
        }

    def _update_token_position_counts(self, seq: list[str]) -> None:
        for idx, token in enumerate(seq):
            key = (idx, token)
            self._token_position_counts[key] = self._token_position_counts.get(key, 0) + 1
            self._position_total_sequences[idx] = self._position_total_sequences.get(idx, 0) + 1

    def _token_position_zscore(self, position: int, token: str) -> float:
        total = int(self._position_total_sequences.get(position, 0))
        if total <= 0:
            return 0.0
        counts = [
            int(count)
            for (pos, _token), count in self._token_position_counts.items()
            if pos == position
        ]
        if len(counts) < 2:
            return 0.0
        mu = sum(counts) / len(counts)
        var = sum((c - mu) ** 2 for c in counts) / len(counts)
        sigma = math.sqrt(max(var, 0.0))
        if sigma <= 1e-12:
            return 0.0
        count = float(self._token_position_counts.get((position, token), 0))
        return (count - mu) / sigma

    def _position_multiplier(self, idx: int, n: int) -> float:
        if n <= 1:
            return 1.0
        return 0.5 + (idx / (n - 1))

    def _impact_weight(self, idx: int, token: str) -> float:
        z = self._token_position_zscore(idx, token)
        if abs(z) < self.rarity_z_threshold:
            return 1.0
        # Smooth weighting to include medium-importance tokens and avoid brittle jumps.
        strength = min(self.impact_weight_cap - 1.0, max(0.0, abs(z)))
        return 1.0 + strength

    def _high_impact_token_positions(self, seq: list[str]) -> dict[str, list[int]]:
        result: dict[str, list[int]] = {}
        for idx, token in enumerate(seq):
            if self._impact_weight(idx, token) <= 1.0:
                continue
            result.setdefault(token, []).append(idx)
        return result

    def _weighted_distance(self, seq_a: list[str], seq_b: list[str]) -> float:
        n = min(len(seq_a), len(seq_b))
        if n == 0:
            return 0.0

        base_distance = 0.0
        impact_distance = 0.0
        for idx in range(n):
            token_a = seq_a[idx]
            token_b = seq_b[idx]
            if token_a == token_b:
                continue
            pos_mult = self._position_multiplier(idx, n)
            wa = self._impact_weight(idx, token_a)
            wb = self._impact_weight(idx, token_b)
            impact_boost = max(wa, wb)
            base_distance += 1.0 * pos_mult
            impact_distance += max(0.0, impact_boost - 1.0) * pos_mult

        # Position check for high-impact token shifts.
        shift_penalty = 0.0
        imp_a = self._high_impact_token_positions(seq_a)
        imp_b = self._high_impact_token_positions(seq_b)
        shared = set(imp_a.keys()) | set(imp_b.keys())
        for token in shared:
            pa = imp_a.get(token, [])
            pb = imp_b.get(token, [])
            if not pa or not pb:
                shift_penalty += 2.0
                continue
            min_shift = min(abs(a - b) for a in pa for b in pb)
            if min_shift > 0:
                shift_penalty += float(min_shift) * 0.75

        return float(base_distance + impact_distance + shift_penalty)

    @staticmethod
    def _entropy_binary(wins: int, losses: int) -> float:
        total = int(wins) + int(losses)
        if total <= 0:
            return 0.0
        p_win = float(wins) / float(total)
        p_loss = float(losses) / float(total)
        entropy = 0.0
        if p_win > 0.0:
            entropy -= p_win * math.log2(p_win)
        if p_loss > 0.0:
            entropy -= p_loss * math.log2(p_loss)
        return float(entropy)

    @staticmethod
    def _win_loss_counts(rows: list[dict[str, object]]) -> tuple[int, int]:
        wins = sum(1 for row in rows if bool(row.get("is_win", False)))
        losses = max(0, len(rows) - wins)
        return int(wins), int(losses)

    def _information_gain(
        self,
        parent_rows: list[dict[str, object]],
        left_rows: list[dict[str, object]],
        right_rows: list[dict[str, object]],
    ) -> float:
        pw, pl = self._win_loss_counts(parent_rows)
        lw, ll = self._win_loss_counts(left_rows)
        rw, rl = self._win_loss_counts(right_rows)
        total = max(1, len(parent_rows))
        parent_entropy = self._entropy_binary(pw, pl)
        left_entropy = self._entropy_binary(lw, ll)
        right_entropy = self._entropy_binary(rw, rl)
        weighted_child = (len(left_rows) / total) * left_entropy + (len(right_rows) / total) * right_entropy
        return float(parent_entropy - weighted_child)

    def _best_divisive_split(
        self,
        rows: list[dict[str, object]],
    ) -> tuple[int, str, float, list[dict[str, object]], list[dict[str, object]]] | None:
        if not rows:
            return None
        min_len = min(len([str(x) for x in row.get("seq", [])]) for row in rows)
        if min_len <= 0:
            return None

        best: tuple[int, str, float, list[dict[str, object]], list[dict[str, object]]] | None = None
        for pos in range(min_len):
            token_candidates = {
                str(seq[pos])
                for seq in ([row.get("seq", []) for row in rows])
                if isinstance(seq, list) and len(seq) > pos
            }
            for token in token_candidates:
                left = [row for row in rows if isinstance(row.get("seq", []), list) and len(row.get("seq", [])) > pos and str(row.get("seq", [])[pos]) == token]
                right = [row for row in rows if row not in left]
                if len(left) < self.tree_min_leaf_samples or len(right) < self.tree_min_leaf_samples:
                    continue
                gain = self._information_gain(rows, left, right)
                if best is None or gain > best[2]:
                    best = (pos, token, float(gain), left, right)
        return best

    def _build_divisive_tree_node(self, rows: list[dict[str, object]], depth: int) -> dict[str, object]:
        wins, losses = self._win_loss_counts(rows)
        support = wins + losses
        node: dict[str, object] = {
            "node_id": int(self._next_tree_node_id),
            "depth": int(depth),
            "wins": int(wins),
            "losses": int(losses),
            "support": int(support),
            "winrate_pct": float((wins / support * 100.0) if support > 0 else 0.0),
            "leaf": True,
        }
        self._next_tree_node_id += 1

        if depth >= self.tree_max_depth:
            return node
        if support < (self.tree_min_leaf_samples * 2):
            return node

        best = self._best_divisive_split(rows)
        if best is None:
            return node
        pos, token, gain, left_rows, right_rows = best
        if float(gain) <= self.tree_min_gain:
            return node

        node["leaf"] = False
        node["split"] = {
            "position": int(pos),
            "token": str(token),
            "gain": float(gain),
        }
        node["left"] = self._build_divisive_tree_node(left_rows, depth + 1)
        node["right"] = self._build_divisive_tree_node(right_rows, depth + 1)
        return node

    def _rebuild_direction_tree(self, predicted_direction: str) -> None:
        rows = [
            row
            for row in self._settled_sequences_by_direction.get(predicted_direction, [])
            if isinstance(row, dict)
        ]
        if len(rows) < (self.tree_min_leaf_samples * 2):
            self._tree_by_direction.pop(predicted_direction, None)
            return
        root = self._build_divisive_tree_node(rows, depth=0)
        root["direction"] = str(predicted_direction)
        self._tree_by_direction[str(predicted_direction)] = root

    def _sequence_embedding(self, seq: list[str], outcome_value: float = 0.0) -> list[float]:
        dim = int(self.hdbscan_embedding_dim)
        vec = [0.0] * dim
        for idx, token in enumerate(seq):
            key = f"{idx}:{token}".encode("utf-8")
            digest = hashlib.blake2b(key, digest_size=8).digest()
            bucket = int.from_bytes(digest, byteorder="big", signed=False) % dim
            vec[bucket] += self._position_multiplier(idx, max(1, len(seq)))
        vec.append(float(outcome_value) * float(self.hdbscan_outcome_weight))
        return vec

    def _rebuild_direction_hdbscan(self, predicted_direction: str) -> None:
        if not _SKLEARN_HDBSCAN_AVAILABLE or SklearnHDBSCAN is None:
            self._hdbscan_clusters_by_direction.pop(predicted_direction, None)
            return
        rows = [
            row
            for row in self._settled_sequences_by_direction.get(predicted_direction, [])
            if isinstance(row, dict)
        ]
        if len(rows) < self.hdbscan_min_cluster_size:
            self._hdbscan_clusters_by_direction.pop(predicted_direction, None)
            return

        x_rows: list[list[float]] = []
        for row in rows:
            seq = [str(x) for x in row.get("seq", [])]
            if not seq:
                continue
            outcome = 1.0 if bool(row.get("is_win", False)) else -1.0
            x_rows.append(self._sequence_embedding(seq=seq, outcome_value=outcome))
        if len(x_rows) < self.hdbscan_min_cluster_size:
            self._hdbscan_clusters_by_direction.pop(predicted_direction, None)
            return

        model = SklearnHDBSCAN(
            min_cluster_size=int(self.hdbscan_min_cluster_size),
            min_samples=int(self.hdbscan_min_samples),
        )
        labels = list(model.fit_predict(x_rows))

        clusters: dict[int, dict[str, object]] = {}
        for idx, label in enumerate(labels):
            if int(label) < 0:
                continue
            row = rows[idx]
            c = clusters.setdefault(
                int(label),
                {
                    "cluster_id": f"hdb-{predicted_direction}-{int(label)}",
                    "direction": str(predicted_direction),
                    "wins": 0,
                    "losses": 0,
                    "support": 0,
                    "prototype": [str(x) for x in row.get("seq", [])],
                },
            )
            c["support"] = int(c.get("support", 0)) + 1
            if bool(row.get("is_win", False)):
                c["wins"] = int(c.get("wins", 0)) + 1
            else:
                c["losses"] = int(c.get("losses", 0)) + 1

        self._hdbscan_clusters_by_direction[str(predicted_direction)] = clusters

    def _hdbscan_signal_from_sequence(self, seq: list[str], predicted_direction: str) -> dict[str, object] | None:
        clusters = self._hdbscan_clusters_by_direction.get(str(predicted_direction), {})
        if not clusters:
            return None
        best: dict[str, object] | None = None
        best_distance: float | None = None
        for cluster in clusters.values():
            prototype = [str(x) for x in cluster.get("prototype", [])]
            if not prototype:
                continue
            distance = self._weighted_distance(seq, prototype)
            if best_distance is None or distance < best_distance:
                best_distance = distance
                best = cluster
        if best is None:
            return None

        wins = int(best.get("wins", 0))
        losses = int(best.get("losses", 0))
        support = wins + losses
        winrate = (wins / support * 100.0) if support > 0 else 0.0
        hi = self.edge_winrate_threshold * 100.0
        lo = (1.0 - self.edge_winrate_threshold) * 100.0
        qualified = support >= self.min_cluster_samples and (winrate >= hi or winrate <= lo)
        return {
            "cluster_id": str(best.get("cluster_id", "NA")),
            "direction": _position_direction_label(str(predicted_direction)),
            "distance": float(best_distance) if best_distance is not None else None,
            "support": int(support),
            "wins": int(wins),
            "losses": int(losses),
            "winrate_pct": float(winrate),
            "qualified": bool(qualified),
            "reason": "ok_hdbscan",
            "source": "hdbscan",
        }

    def _record_settled_sequence(self, seq: list[str], predicted_direction: str, is_win: bool) -> None:
        direction = str(predicted_direction)
        if direction not in {"BULL", "BEAR"}:
            return
        rows = self._settled_sequences_by_direction.setdefault(direction, [])
        rows.append({
            "seq": list(seq),
            "is_win": bool(is_win),
        })
        if len(rows) > self.tree_history_cap:
            del rows[0 : len(rows) - self.tree_history_cap]

        should_rebuild_tree = len(rows) <= self.tree_rebuild_interval or (len(rows) % self.tree_rebuild_interval == 0)
        if should_rebuild_tree:
            self._rebuild_direction_tree(direction)
        if self.cluster_mode_active == "hdbscan":
            should_rebuild_hdbscan = len(rows) <= self.hdbscan_rebuild_interval or (len(rows) % self.hdbscan_rebuild_interval == 0)
            if should_rebuild_hdbscan:
                self._rebuild_direction_hdbscan(direction)

    def _tree_signal_from_current_window(self, seq: list[str], predicted_direction: str) -> dict[str, object] | None:
        root = self._tree_by_direction.get(str(predicted_direction))
        if not root or not isinstance(root, dict):
            return None

        node: dict[str, object] = root
        path: list[str] = []
        gain_sum = 0.0
        while not bool(node.get("leaf", True)):
            split = node.get("split", {}) if isinstance(node.get("split", {}), dict) else {}
            pos = int(split.get("position", -1))
            token = str(split.get("token", "NA"))
            gain = float(split.get("gain", 0.0))
            seq_token = seq[pos] if 0 <= pos < len(seq) else "NA"
            go_left = seq_token == token
            path.append(f"p{pos + 1}{'==' if go_left else '!='}{token}")
            gain_sum += gain
            next_node = node.get("left" if go_left else "right")
            if not isinstance(next_node, dict):
                break
            node = next_node

        wins = int(node.get("wins", 0))
        losses = int(node.get("losses", 0))
        support = wins + losses
        winrate = float((wins / support * 100.0) if support > 0 else 0.0)
        hi = self.edge_winrate_threshold * 100.0
        lo = (1.0 - self.edge_winrate_threshold) * 100.0
        qualified = support >= self.min_cluster_samples and (winrate >= hi or winrate <= lo)

        return {
            "cluster_id": f"tree-{int(node.get('node_id', 0))}",
            "direction": _position_direction_label(str(predicted_direction)),
            "distance": None,
            "support": int(support),
            "wins": int(wins),
            "losses": int(losses),
            "winrate_pct": float(winrate),
            "qualified": bool(qualified),
            "reason": "ok_tree",
            "source": "tree",
            "tree_path": "root" if not path else f"root->{'/'.join(path)}",
            "tree_gain_sum": float(gain_sum),
        }

    def _cluster_stats_view(self, cluster: dict[str, object], distance: float | None = None) -> dict[str, object]:
        wins = int(cluster.get("wins", 0))
        losses = int(cluster.get("losses", 0))
        support = wins + losses
        winrate = (wins / support * 100.0) if support > 0 else 0.0
        hi = self.edge_winrate_threshold * 100.0
        lo = (1.0 - self.edge_winrate_threshold) * 100.0
        qualified = support >= self.min_cluster_samples and (winrate >= hi or winrate <= lo)
        return {
            "cluster_id": int(cluster.get("cluster_id", 0)),
            "direction": _position_direction_label(str(cluster.get("direction", "BULL"))),
            "distance": distance,
            "support": support,
            "wins": wins,
            "losses": losses,
            "winrate_pct": winrate,
            "qualified": qualified,
        }

    def _cluster_support_winrate(self, cluster: dict[str, object]) -> tuple[int, float]:
        wins = int(cluster.get("wins", 0))
        losses = int(cluster.get("losses", 0))
        support = wins + losses
        winrate = (wins / support) if support > 0 else 0.0
        return support, winrate

    def _effective_threshold_for_cluster(self, cluster: dict[str, object]) -> float:
        support, winrate = self._cluster_support_winrate(cluster)
        threshold = float(self.distance_threshold)
        if support >= self.purity_split_min_support and winrate >= self.purity_split_winrate_threshold:
            threshold *= self.purity_split_tighten_factor
        return max(0.1, float(threshold))

    def _high_impact_position_token_set(self, seq: list[str]) -> set[tuple[int, str]]:
        result: set[tuple[int, str]] = set()
        for idx, token in enumerate(seq):
            if self._impact_weight(idx, token) > 1.0:
                result.add((idx, token))
        return result

    def _has_high_impact_outlier(self, seq: list[str], exemplar: list[str]) -> bool:
        seq_imp = self._high_impact_position_token_set(seq)
        ex_imp = self._high_impact_position_token_set(exemplar)
        outliers = seq_imp - ex_imp
        return len(outliers) >= self.purity_split_min_outliers

    def _closest_cluster(self, seq: list[str], predicted_direction: str) -> tuple[dict[str, object] | None, float | None]:
        best_cluster: dict[str, object] | None = None
        best_distance: float | None = None
        for cluster in self._clusters.values():
            if str(cluster.get("direction")) != predicted_direction:
                continue
            exemplar = [str(x) for x in cluster.get("exemplar", [])]
            if not exemplar:
                continue
            distance = self._weighted_distance(seq, exemplar)
            if best_distance is None or distance < best_distance:
                best_distance = distance
                best_cluster = cluster
        return best_cluster, best_distance

    def _assign_and_update_cluster(
        self,
        seq: list[str],
        predicted_direction: str,
        is_win: bool,
    ) -> dict[str, object]:
        cluster, distance = self._closest_cluster(seq, predicted_direction)
        assignment_mode = "join_existing"
        split_reason = "none"
        effective_threshold = float(self.distance_threshold)

        if cluster is not None:
            effective_threshold = self._effective_threshold_for_cluster(cluster)

        force_new = cluster is None or distance is None or distance > effective_threshold
        if force_new:
            assignment_mode = "new_cluster"
            split_reason = "distance_gate"
        elif cluster is not None:
            support, winrate = self._cluster_support_winrate(cluster)
            exemplar = [str(x) for x in cluster.get("exemplar", [])]
            if (
                support >= self.purity_split_min_support
                and winrate >= self.purity_split_winrate_threshold
                and self._has_high_impact_outlier(seq=seq, exemplar=exemplar)
            ):
                force_new = True
                assignment_mode = "split_for_purity"
                split_reason = "high_winrate_outlier"

        if force_new:
            cluster_id = self._next_cluster_id
            self._next_cluster_id += 1
            cluster = {
                "cluster_id": cluster_id,
                "direction": predicted_direction,
                "exemplar": list(seq),
                "wins": 0,
                "losses": 0,
            }
            self._clusters[cluster_id] = cluster
            distance = 0.0

        if is_win:
            cluster["wins"] = int(cluster.get("wins", 0)) + 1
        else:
            cluster["losses"] = int(cluster.get("losses", 0)) + 1
        view = self._cluster_stats_view(cluster, distance=distance)
        view["assignment_mode"] = assignment_mode
        view["effective_threshold"] = float(effective_threshold)
        view["split_reason"] = split_reason
        view["source"] = "cluster"
        return view

    def cluster_signal_from_current_window(self, predicted_direction: str) -> dict[str, object]:
        seq = list(self._rolling_tokens)
        if len(seq) < self.sequence_len:
            self._last_cluster_signal = {
                "cluster_id": None,
                "direction": _position_direction_label(predicted_direction),
                "distance": None,
                "support": 0,
                "wins": 0,
                "losses": 0,
                "winrate_pct": 0.0,
                "qualified": False,
                "reason": "insufficient_sequence_window",
                "source": "cluster",
            }
            return dict(self._last_cluster_signal)

        if self.cluster_mode_active == "hdbscan":
            hdbscan_signal = self._hdbscan_signal_from_sequence(seq=seq, predicted_direction=predicted_direction)
            if hdbscan_signal is not None:
                self._last_cluster_signal = dict(hdbscan_signal)
                return dict(self._last_cluster_signal)

        tree_signal = self._tree_signal_from_current_window(seq=seq, predicted_direction=predicted_direction)
        if tree_signal is not None:
            self._last_cluster_signal = dict(tree_signal)
            return dict(self._last_cluster_signal)

        cluster, distance = self._closest_cluster(seq, predicted_direction)
        effective_threshold = (
            self._effective_threshold_for_cluster(cluster)
            if cluster is not None
            else float(self.distance_threshold)
        )
        if cluster is None or distance is None or distance > effective_threshold:
            self._last_cluster_signal = {
                "cluster_id": None,
                "direction": _position_direction_label(predicted_direction),
                "distance": distance,
                "support": 0,
                "wins": 0,
                "losses": 0,
                "winrate_pct": 0.0,
                "qualified": False,
                "reason": "no_cluster_match",
                "effective_threshold": float(effective_threshold),
                "source": "cluster",
            }
            return dict(self._last_cluster_signal)

        view = self._cluster_stats_view(cluster, distance=distance)
        view["reason"] = "ok"
        view["effective_threshold"] = float(effective_threshold)
        view["source"] = "cluster"
        self._last_cluster_signal = view
        return dict(self._last_cluster_signal)

    def last_cluster_signal(self) -> dict[str, object]:
        return dict(self._last_cluster_signal)

    def fuzzy_bias_from_current_window(
        self,
        min_support_sequences: int = 3,
        top_k: int = 5,
    ) -> dict[str, object]:
        total_wins = int(self._win_sequences)
        total_losses = int(self._loss_sequences)
        if total_wins <= 0 or total_losses <= 0:
            return {
                "score": 0.0,
                "signal": "Neutral",
                "matched": 0,
                "support_sum": 0,
                "top_positive": [],
                "top_negative": [],
                "reason": "insufficient_win_loss_sequences",
            }

        current_fragments: set[str] = set()
        for token in self._rolling_tokens:
            current_fragments.update(self._token_fragments(token))

        matched_rows: list[dict[str, object]] = []
        for fragment in current_fragments:
            wins, losses = self._fragment_stats.get(fragment, (0, 0))
            support = int(wins + losses)
            if support < max(1, int(min_support_sequences)):
                continue
            win_freq = wins / total_wins
            loss_freq = losses / total_losses
            delta = float(win_freq - loss_freq)
            matched_rows.append(
                {
                    "fragment": fragment,
                    "delta": delta,
                    "support": support,
                }
            )

        if not matched_rows:
            return {
                "score": 0.0,
                "signal": "Neutral",
                "matched": 0,
                "support_sum": 0,
                "top_positive": [],
                "top_negative": [],
                "reason": "no_supported_fragment_match",
            }

        support_sum = int(sum(int(row["support"]) for row in matched_rows))
        weighted_score_num = sum(float(row["delta"]) * int(row["support"]) for row in matched_rows)
        score = weighted_score_num / max(float(support_sum), 1.0)

        if score > 0.05:
            signal = "Bullish"
        elif score < -0.05:
            signal = "Bearish"
        else:
            signal = "Neutral"

        matched_rows.sort(key=lambda r: abs(float(r["delta"])), reverse=True)
        positives = [row for row in matched_rows if float(row["delta"]) > 0][: max(1, int(top_k))]
        negatives = [row for row in matched_rows if float(row["delta"]) < 0][: max(1, int(top_k))]

        return {
            "score": float(score),
            "signal": signal,
            "matched": int(len(matched_rows)),
            "support_sum": support_sum,
            "top_positive": positives,
            "top_negative": negatives,
            "reason": "ok",
        }

    def winloss_rows(self, limit: int = 40) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for (position, feature, label), (wins, total) in self._position_stats.items():
            winrate_pct = (wins / total * 100.0) if total else 0.0
            rows.append(
                {
                    "position": position,
                    "feature": feature,
                    "label": label,
                    "wins": wins,
                    "total": total,
                    "winrate_pct": winrate_pct,
                    "commonality": self._commonality_from_winrate(winrate_pct),
                }
            )
        rows.sort(key=lambda r: (int(r["total"]), abs(float(r["winrate_pct"]) - 50.0)), reverse=True)
        return rows[:limit]

    def position_winrate_rows(self, limit: int = 25) -> list[dict[str, object]]:
        by_position: dict[int, tuple[int, int]] = {}
        for (position, _feature, _label), (wins, total) in self._position_stats.items():
            agg_wins, agg_total = by_position.get(position, (0, 0))
            by_position[position] = (agg_wins + int(wins), agg_total + int(total))

        rows: list[dict[str, object]] = []
        for position in sorted(by_position.keys()):
            wins, total = by_position[position]
            winrate_pct = (wins / total * 100.0) if total else 0.0
            rows.append(
                {
                    "position": int(position),
                    "wins": int(wins),
                    "total": int(total),
                    "winrate_pct": float(winrate_pct),
                    "commonality": self._commonality_from_winrate(winrate_pct),
                }
            )
        return rows[: max(1, int(limit))]

    def gradient_rows(self, limit: int = 40) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        total_wins = max(1, self._win_sequences)
        total_losses = max(1, self._loss_sequences)
        for fragment, (fragment_wins, fragment_losses) in self._fragment_stats.items():
            win_freq = fragment_wins / total_wins
            loss_freq = fragment_losses / total_losses
            delta = win_freq - loss_freq
            if delta > 0.15:
                signal = "Bullish"
            elif delta < -0.15:
                signal = "Bearish"
            else:
                signal = "Neutral"
            rows.append(
                {
                    "fragment": fragment,
                    "fragment_wins": fragment_wins,
                    "fragment_losses": fragment_losses,
                    "win_freq": win_freq,
                    "loss_freq": loss_freq,
                    "delta": delta,
                    "signal": signal,
                }
            )
        rows.sort(key=lambda r: (abs(float(r["delta"])), int(r["fragment_wins"]) + int(r["fragment_losses"])), reverse=True)
        return rows[:limit]

    def ngram_rows(self, limit: int = 40) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        total_wins = max(1, self._win_sequences)
        total_losses = max(1, self._loss_sequences)
        for pattern, (wins, losses) in self._ngram_stats.items():
            support = wins + losses
            win_freq = wins / total_wins
            loss_freq = losses / total_losses
            win_rate = (wins / support) if support else 0.0
            rows.append(
                {
                    "pattern": pattern,
                    "support": support,
                    "wins": wins,
                    "losses": losses,
                    "win_freq": win_freq,
                    "loss_freq": loss_freq,
                    "win_rate": win_rate,
                }
            )
        rows.sort(key=lambda r: (int(r["support"]), abs(float(r["win_freq"]) - float(r["loss_freq"]))), reverse=True)
        return rows[:limit]

    def dump_state(self) -> dict:
        return {
            "sequence_len": self.sequence_len,
            "ngram_size": self.ngram_size,
            "cluster_mode_requested": self.cluster_mode_requested,
            "cluster_mode_active": self.cluster_mode_active,
            "rarity_z_threshold": self.rarity_z_threshold,
            "impact_weight_cap": self.impact_weight_cap,
            "distance_threshold": self.distance_threshold,
            "min_cluster_samples": self.min_cluster_samples,
            "edge_winrate_threshold": self.edge_winrate_threshold,
            "purity_split_winrate_threshold": self.purity_split_winrate_threshold,
            "purity_split_min_support": self.purity_split_min_support,
            "purity_split_tighten_factor": self.purity_split_tighten_factor,
            "purity_split_min_outliers": self.purity_split_min_outliers,
            "tree_rebuild_interval": self.tree_rebuild_interval,
            "tree_min_leaf_samples": self.tree_min_leaf_samples,
            "tree_max_depth": self.tree_max_depth,
            "tree_min_gain": self.tree_min_gain,
            "tree_history_cap": self.tree_history_cap,
            "hdbscan_min_cluster_size": self.hdbscan_min_cluster_size,
            "hdbscan_min_samples": self.hdbscan_min_samples,
            "hdbscan_rebuild_interval": self.hdbscan_rebuild_interval,
            "hdbscan_outcome_weight": self.hdbscan_outcome_weight,
            "hdbscan_embedding_dim": self.hdbscan_embedding_dim,
            "rolling_tokens": list(self._rolling_tokens),
            "snapshot_by_minute": dict(self._snapshot_by_minute),
            "position_stats": [
                {
                    "position": p,
                    "feature": f,
                    "label": l,
                    "wins": w,
                    "total": t,
                }
                for (p, f, l), (w, t) in self._position_stats.items()
            ],
            "fragment_stats": [
                {"fragment": k, "wins": w, "losses": l}
                for k, (w, l) in self._fragment_stats.items()
            ],
            "ngram_stats": [
                {"pattern": k, "wins": w, "losses": l}
                for k, (w, l) in self._ngram_stats.items()
            ],
            "win_sequences": self._win_sequences,
            "loss_sequences": self._loss_sequences,
            "partial_sequences": self._partial_sequences,
            "full_sequences": self._full_sequences,
            "token_position_counts": [
                {
                    "position": pos,
                    "token": token,
                    "count": count,
                }
                for (pos, token), count in self._token_position_counts.items()
            ],
            "position_total_sequences": dict(self._position_total_sequences),
            "clusters": list(self._clusters.values()),
            "next_cluster_id": self._next_cluster_id,
            "settled_sequences_by_direction": dict(self._settled_sequences_by_direction),
            "tree_by_direction": dict(self._tree_by_direction),
            "hdbscan_clusters_by_direction": dict(self._hdbscan_clusters_by_direction),
            "next_tree_node_id": self._next_tree_node_id,
            "last_cluster_signal": dict(self._last_cluster_signal),
        }

    @classmethod
    def from_state(cls, state: dict) -> "SymbolicPatternTracker":
        obj = cls(
            sequence_len=int(state.get("sequence_len", 25)),
            ngram_size=int(state.get("ngram_size", 3)),
            cluster_mode=str(state.get("cluster_mode_requested", "tree")),
            rarity_z_threshold=float(state.get("rarity_z_threshold", 2.5)),
            impact_weight_cap=float(state.get("impact_weight_cap", 10.0)),
            distance_threshold=float(state.get("distance_threshold", 9.0)),
            min_cluster_samples=int(state.get("min_cluster_samples", 30)),
            edge_winrate_threshold=float(state.get("edge_winrate_threshold", 0.60)),
            purity_split_winrate_threshold=float(state.get("purity_split_winrate_threshold", 0.75)),
            purity_split_min_support=int(state.get("purity_split_min_support", 30)),
            purity_split_tighten_factor=float(state.get("purity_split_tighten_factor", 0.60)),
            purity_split_min_outliers=int(state.get("purity_split_min_outliers", 1)),
            tree_rebuild_interval=int(state.get("tree_rebuild_interval", 25)),
            tree_min_leaf_samples=int(state.get("tree_min_leaf_samples", 20)),
            tree_max_depth=int(state.get("tree_max_depth", 4)),
            tree_min_gain=float(state.get("tree_min_gain", 0.005)),
            tree_history_cap=int(state.get("tree_history_cap", 5000)),
            hdbscan_min_cluster_size=int(state.get("hdbscan_min_cluster_size", 20)),
            hdbscan_min_samples=int(state.get("hdbscan_min_samples", 10)),
            hdbscan_rebuild_interval=int(state.get("hdbscan_rebuild_interval", 25)),
            hdbscan_outcome_weight=float(state.get("hdbscan_outcome_weight", 2.0)),
            hdbscan_embedding_dim=int(state.get("hdbscan_embedding_dim", 256)),
        )
        obj._rolling_tokens = deque(
            (str(t) for t in state.get("rolling_tokens", [])),
            maxlen=obj.sequence_len,
        )
        # Backward-compatible hydrate: older state stored list[str], newer stores dict payload.
        for key, value in state.get("snapshot_by_minute", {}).items():
            if isinstance(value, dict):
                seq = [str(x) for x in value.get("seq", [])]
                direction = str(value.get("predicted_direction", "BULL"))
            else:
                seq = [str(x) for x in value]
                direction = "BULL"
            obj._snapshot_by_minute[str(key)] = {
                "seq": seq,
                "predicted_direction": direction,
            }
        for row in state.get("position_stats", []):
            key = (int(row["position"]), str(row["feature"]), str(row["label"]))
            obj._position_stats[key] = (int(row["wins"]), int(row["total"]))
        for row in state.get("fragment_stats", []):
            obj._fragment_stats[str(row["fragment"])] = (int(row["wins"]), int(row["losses"]))
        for row in state.get("ngram_stats", []):
            obj._ngram_stats[str(row["pattern"])] = (int(row["wins"]), int(row["losses"]))
        obj._win_sequences = int(state.get("win_sequences", 0))
        obj._loss_sequences = int(state.get("loss_sequences", 0))
        obj._partial_sequences = int(state.get("partial_sequences", 0))
        obj._full_sequences = int(state.get("full_sequences", 0))
        for row in state.get("token_position_counts", []):
            key = (int(row["position"]), str(row["token"]))
            obj._token_position_counts[key] = int(row["count"])
        obj._position_total_sequences = {
            int(k): int(v)
            for k, v in state.get("position_total_sequences", {}).items()
        }
        obj._clusters = {
            int(row.get("cluster_id", i + 1)): {
                "cluster_id": int(row.get("cluster_id", i + 1)),
                "direction": str(row.get("direction", "BULL")),
                "exemplar": [str(x) for x in row.get("exemplar", [])],
                "wins": int(row.get("wins", 0)),
                "losses": int(row.get("losses", 0)),
            }
            for i, row in enumerate(state.get("clusters", []))
        }
        obj._next_cluster_id = int(state.get("next_cluster_id", len(obj._clusters) + 1))
        raw_settled = state.get("settled_sequences_by_direction", {})
        if isinstance(raw_settled, dict):
            obj._settled_sequences_by_direction = {
                "BULL": [row for row in raw_settled.get("BULL", []) if isinstance(row, dict)],
                "BEAR": [row for row in raw_settled.get("BEAR", []) if isinstance(row, dict)],
            }
        raw_tree = state.get("tree_by_direction", {})
        if isinstance(raw_tree, dict):
            obj._tree_by_direction = {
                str(k): v
                for k, v in raw_tree.items()
                if isinstance(v, dict)
            }
        raw_hdbscan = state.get("hdbscan_clusters_by_direction", {})
        if isinstance(raw_hdbscan, dict):
            obj._hdbscan_clusters_by_direction = {
                str(direction): {
                    int(k): v for k, v in clusters.items() if isinstance(v, dict)
                }
                for direction, clusters in raw_hdbscan.items()
                if isinstance(clusters, dict)
            }
        obj._next_tree_node_id = int(state.get("next_tree_node_id", 1))
        obj._last_cluster_signal = dict(
            state.get(
                "last_cluster_signal",
                {
                    "cluster_id": None,
                    "direction": "NA",
                    "distance": None,
                    "support": 0,
                    "winrate_pct": 0.0,
                    "qualified": False,
                    "source": "cluster",
                },
            )
        )
        return obj


class OBLMEngine:
    def __init__(
        self,
        quantizer: AdaptiveQuantizer | None = None,
        model: IncrementalOBLMModel | None = None,
        calibration: CalibrationTracker | None = None,
        indicator_state: RollingIndicatorState | None = None,
        pattern_tracker: SymbolicPatternTracker | None = None,
        holding_minutes: int = 5,
        fuzzy_bias_weight: float = 0.25,
        fuzzy_min_support_sequences: int = 3,
        warmup_candles: int = 10080,
        enable_no_trade_gate: bool = False,
        no_trade_uncertainty_threshold: float = 0.72,
        trading_session_enabled: bool = False,
        trading_session_weekdays_only: bool = True,
        trading_session_start_hour_utc: int = 9,
        trading_session_end_hour_utc: int = 19,
        cluster_mode: str = "tree",
        cluster_rarity_z_threshold: float = 2.5,
        cluster_impact_weight_cap: float = 10.0,
        cluster_distance_threshold: float = 9.0,
        cluster_min_samples: int = 30,
        cluster_edge_winrate_threshold: float = 0.60,
        cluster_purity_split_winrate_threshold: float = 0.75,
        cluster_purity_split_min_support: int = 30,
        cluster_purity_split_tighten_factor: float = 0.60,
        cluster_purity_split_min_outliers: int = 1,
        cluster_tree_rebuild_interval: int = 25,
        cluster_tree_min_leaf_samples: int = 20,
        cluster_tree_max_depth: int = 4,
        cluster_tree_min_gain: float = 0.005,
        cluster_tree_history_cap: int = 5000,
        cluster_hdbscan_min_cluster_size: int = 20,
        cluster_hdbscan_min_samples: int = 10,
        cluster_hdbscan_rebuild_interval: int = 25,
        cluster_hdbscan_outcome_weight: float = 2.0,
        cluster_hdbscan_embedding_dim: int = 256,
    ):
        self._quantizer = quantizer or AdaptiveQuantizer(rolling_window=10080)
        self._model = model or IncrementalOBLMModel()
        self._calibration = calibration or CalibrationTracker()
        self._indicator_state = indicator_state or RollingIndicatorState(rolling_window=10080)
        self._pattern_tracker = pattern_tracker or SymbolicPatternTracker(
            sequence_len=25,
            ngram_size=3,
            cluster_mode=cluster_mode,
            rarity_z_threshold=cluster_rarity_z_threshold,
            impact_weight_cap=cluster_impact_weight_cap,
            distance_threshold=cluster_distance_threshold,
            min_cluster_samples=cluster_min_samples,
            edge_winrate_threshold=cluster_edge_winrate_threshold,
            purity_split_winrate_threshold=cluster_purity_split_winrate_threshold,
            purity_split_min_support=cluster_purity_split_min_support,
            purity_split_tighten_factor=cluster_purity_split_tighten_factor,
            purity_split_min_outliers=cluster_purity_split_min_outliers,
            tree_rebuild_interval=cluster_tree_rebuild_interval,
            tree_min_leaf_samples=cluster_tree_min_leaf_samples,
            tree_max_depth=cluster_tree_max_depth,
            tree_min_gain=cluster_tree_min_gain,
            tree_history_cap=cluster_tree_history_cap,
            hdbscan_min_cluster_size=cluster_hdbscan_min_cluster_size,
            hdbscan_min_samples=cluster_hdbscan_min_samples,
            hdbscan_rebuild_interval=cluster_hdbscan_rebuild_interval,
            hdbscan_outcome_weight=cluster_hdbscan_outcome_weight,
            hdbscan_embedding_dim=cluster_hdbscan_embedding_dim,
        )
        self._holding_minutes = max(1, int(holding_minutes))
        self._fuzzy_bias_weight = min(max(float(fuzzy_bias_weight), 0.0), 1.0)
        self._fuzzy_min_support_sequences = max(1, int(fuzzy_min_support_sequences))
        self._warmup_candles = max(0, int(warmup_candles))
        self._enable_no_trade_gate = bool(enable_no_trade_gate)
        self._no_trade_uncertainty_threshold = min(
            max(float(no_trade_uncertainty_threshold), 0.0),
            1.0,
        )
        self._trading_session_enabled = bool(trading_session_enabled)
        self._trading_session_weekdays_only = bool(trading_session_weekdays_only)
        self._trading_session_start_hour_utc = int(trading_session_start_hour_utc) % 24
        self._trading_session_end_hour_utc = int(trading_session_end_hour_utc) % 24
        self._candles_seen = 0

        self._pending: deque[PendingPrediction] = deque()
        self._last_token: str | None = None
        self._last_indicator_context: dict[str, float | None] = {}
        self._last_settlements: list[dict[str, object]] = []
        self._last_fuzzy_bias: dict[str, object] = {}
        self._last_model_input: str = ""
        self._last_uncertainty: float = 0.0
        self._last_action: str = "TRADE"
        self._last_reason: str = "ok"
        self._last_warmup_remaining: int = max(0, self._warmup_candles)
        self._last_cluster_signal: dict[str, object] = {
            "cluster_id": None,
            "direction": "NA",
            "distance": None,
            "support": 0,
            "wins": 0,
            "losses": 0,
            "winrate_pct": 0.0,
            "qualified": False,
            "reason": "boot",
        }

    def _compute_uncertainty(
        self,
        p_bull: float,
        fuzzy_bias: dict[str, object],
    ) -> dict[str, object]:
        margin = abs(float(p_bull) - 0.5)
        confidence_uncertainty = 1.0 - min(margin / 0.25, 1.0)

        fuzzy_score = float(fuzzy_bias.get("score", 0.0))
        fuzzy_uncertainty = 1.0 - min(abs(fuzzy_score) / 0.12, 1.0)

        support_sum = int(fuzzy_bias.get("support_sum", 0))
        support_uncertainty = 1.0 - min(float(support_sum) / 200.0, 1.0)

        matched = int(fuzzy_bias.get("matched", 0))
        matched_uncertainty = 1.0 - min(float(matched) / 20.0, 1.0)

        has_pos = bool(fuzzy_bias.get("top_positive"))
        has_neg = bool(fuzzy_bias.get("top_negative"))
        conflict_uncertainty = 1.0 if (has_pos and has_neg) else 0.0

        score = (
            0.35 * confidence_uncertainty
            + 0.35 * fuzzy_uncertainty
            + 0.15 * support_uncertainty
            + 0.05 * matched_uncertainty
            + 0.10 * conflict_uncertainty
        )
        score = min(max(float(score), 0.0), 1.0)

        reasons: list[str] = []
        if confidence_uncertainty >= 0.7:
            reasons.append("low_model_margin")
        if fuzzy_uncertainty >= 0.7:
            reasons.append("fuzzy_near_neutral")
        if support_uncertainty >= 0.6:
            reasons.append("low_fuzzy_support")
        if conflict_uncertainty >= 1.0:
            reasons.append("mixed_fragment_signals")
        if not reasons:
            reasons.append("stable")

        return {
            "score": score,
            "reasons": reasons,
            "components": {
                "confidence_uncertainty": confidence_uncertainty,
                "fuzzy_uncertainty": fuzzy_uncertainty,
                "support_uncertainty": support_uncertainty,
                "matched_uncertainty": matched_uncertainty,
                "conflict_uncertainty": conflict_uncertainty,
            },
        }

    def _new_pending(
        self,
        minute: datetime,
        token: str,
        model_input: str,
        close_price: float,
        predicted_direction: str,
        bull_probability: float,
    ) -> PendingPrediction:
        return PendingPrediction(
            minute=minute,
            token=token,
            model_input=model_input,
            reference_price=close_price,
            predicted_direction=predicted_direction,
            bull_probability=bull_probability,
        )

    def _settle_after_holding(self, current_close: float, current_minute: datetime) -> list[dict[str, object]]:
        settled: list[dict[str, object]] = []
        remaining: deque[PendingPrediction] = deque()

        while self._pending:
            pending = self._pending.popleft()
            age_minutes = max(
                0,
                int((_minute_floor(current_minute) - _minute_floor(pending.minute)).total_seconds() // 60),
            )
            if age_minutes < self._holding_minutes:
                remaining.append(pending)
                continue

            settle_reason = "time_exit"
            if pending.predicted_direction == "BULL":
                is_win = current_close > pending.reference_price
            else:
                is_win = current_close < pending.reference_price

            confidence = (
                pending.bull_probability
                if pending.predicted_direction == "BULL"
                else 1.0 - pending.bull_probability
            )
            realized_label = (
                pending.predicted_direction if is_win else _opposite_direction(pending.predicted_direction)
            )
            self._model.update(pending.model_input, realized_label)
            self._calibration.update(confidence=confidence, correct=is_win)
            analytics = self._pattern_tracker.settle_prediction(minute=pending.minute, is_win=is_win)

            settled.append(
                {
                    "pred_minute": pending.minute.isoformat(),
                    "reference_price": pending.reference_price,
                    "eval_price": current_close,
                    "predicted": pending.predicted_direction,
                    "realized": realized_label,
                    "correct": is_win,
                    "confidence": confidence,
                    "exit_price": current_close,
                    "settle_reason": settle_reason,
                    "age_minutes": age_minutes,
                    **analytics,
                }
            )

        self._pending = remaining
        return settled

    def process_market_state(self, state: MarketState) -> PredictionOutput:
        minute = _minute_floor(state.timestamp)
        self._candles_seen += 1
        warmup_remaining = max(0, self._warmup_candles - self._candles_seen)
        self._last_warmup_remaining = warmup_remaining

        indicator_context = self._indicator_state.update(state.candle)
        self._last_indicator_context = dict(indicator_context)
        token = self._quantizer.to_token(state=state, indicator_context=indicator_context)
        self._last_token = token
        # Always advance symbolic context window, even during warmup/NO_TRADE.
        # This prevents bootstrap counters from appearing frozen while waiting to trade.
        self._pattern_tracker.observe_token(token)
        model_input = _build_syllable_model_input(token, include_interactions=True)
        self._last_model_input = model_input

        base_p_bull = self._model.predict_bull_probability(model_input)
        fuzzy_bias = self._pattern_tracker.fuzzy_bias_from_current_window(
            min_support_sequences=self._fuzzy_min_support_sequences,
            top_k=5,
        )
        self._last_fuzzy_bias = dict(fuzzy_bias)
        fuzzy_score = float(fuzzy_bias.get("score", 0.0))
        p_bull = min(max(base_p_bull + (self._fuzzy_bias_weight * fuzzy_score), 0.0), 1.0)
        uncertainty_meta = self._compute_uncertainty(p_bull=p_bull, fuzzy_bias=fuzzy_bias)
        uncertainty = float(uncertainty_meta["score"])
        predicted_direction = "BULL" if p_bull >= 0.5 else "BEAR"
        self._last_cluster_signal = self._pattern_tracker.cluster_signal_from_current_window(
            predicted_direction=predicted_direction,
        )
        confidence = p_bull if predicted_direction == "BULL" else 1.0 - p_bull
        action = "TRADE"
        reason = "ok"
        if warmup_remaining > 0:
            action = "NO_TRADE"
            reason = f"warmup_countdown:{warmup_remaining}"
        elif not _is_trading_session_open(
            minute=minute,
            enabled=self._trading_session_enabled,
            weekdays_only=self._trading_session_weekdays_only,
            start_hour_utc=self._trading_session_start_hour_utc,
            end_hour_utc=self._trading_session_end_hour_utc,
        ):
            action = "NO_TRADE"
            reason = "outside_trading_session"
        elif self._enable_no_trade_gate and uncertainty >= self._no_trade_uncertainty_threshold:
            action = "NO_TRADE"
            reason = "|".join(str(x) for x in uncertainty_meta.get("reasons", []))

        self._last_uncertainty = uncertainty
        self._last_action = action
        self._last_reason = reason
        prediction = PredictionOutput(
            direction=predicted_direction,
            probability=float(confidence),
            timestamp=_minute_floor(minute).isoformat(),
            action=action,
            uncertainty=uncertainty,
            reason=reason,
        )

        if action == "TRADE":
            pending = self._new_pending(
                minute=minute,
                token=token,
                model_input=model_input,
                close_price=state.candle.close,
                predicted_direction=predicted_direction,
                bull_probability=p_bull,
            )
            self._pending.append(pending)
            self._pattern_tracker.snapshot_prediction(
                minute=minute,
                predicted_direction=predicted_direction,
            )

        self._last_settlements = self._settle_after_holding(
            current_close=state.candle.close,
            current_minute=minute,
        )
        return prediction

    def calibration_summary(self) -> dict[str, float | int]:
        return self._calibration.summary()

    def symbolic_summary_rows(self) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        return (
            self._pattern_tracker.winloss_rows(limit=40),
            self._pattern_tracker.gradient_rows(limit=40),
        )

    def symbolic_position_rows(self) -> list[dict[str, object]]:
        return self._pattern_tracker.position_winrate_rows(limit=25)

    def symbolic_bootstrap_status(self) -> dict[str, int]:
        return self._pattern_tracker.bootstrap_status()

    @property
    def last_token(self) -> str | None:
        return self._last_token

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    @property
    def warmed_up(self) -> bool:
        return self._candles_seen >= self._warmup_candles

    @property
    def last_settlements(self) -> list[dict[str, object]]:
        return list(self._last_settlements)

    @property
    def last_indicator_context(self) -> dict[str, float | None]:
        return dict(self._last_indicator_context)

    @property
    def last_fuzzy_bias(self) -> dict[str, object]:
        return dict(self._last_fuzzy_bias)

    @property
    def last_uncertainty(self) -> float:
        return float(self._last_uncertainty)

    @property
    def last_action(self) -> str:
        return str(self._last_action)

    @property
    def last_reason(self) -> str:
        return str(self._last_reason)

    @property
    def last_model_input(self) -> str:
        return self._last_model_input

    @property
    def warmup_remaining(self) -> int:
        return int(self._last_warmup_remaining)

    @property
    def last_cluster_signal(self) -> dict[str, object]:
        return dict(self._last_cluster_signal)

    def dump_state(self) -> dict:
        return {
            "model_feature_regime": MODEL_FEATURE_REGIME,
            "quantizer": self._quantizer.dump_state(),
            "model": self._model.dump_state(),
            "calibration": self._calibration.dump_state(),
            "indicator_state": self._indicator_state.dump_state(),
            "pattern_tracker": self._pattern_tracker.dump_state(),
            "holding_minutes": self._holding_minutes,
            "fuzzy_bias_weight": self._fuzzy_bias_weight,
            "fuzzy_min_support_sequences": self._fuzzy_min_support_sequences,
            "warmup_candles": self._warmup_candles,
            "enable_no_trade_gate": self._enable_no_trade_gate,
            "no_trade_uncertainty_threshold": self._no_trade_uncertainty_threshold,
            "trading_session_enabled": self._trading_session_enabled,
            "trading_session_weekdays_only": self._trading_session_weekdays_only,
            "trading_session_start_hour_utc": self._trading_session_start_hour_utc,
            "trading_session_end_hour_utc": self._trading_session_end_hour_utc,
            "candles_seen": self._candles_seen,
            "pending": [
                {
                    "minute": p.minute.isoformat(),
                    "token": p.token,
                    "model_input": p.model_input,
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

        if state.get("model_feature_regime") != MODEL_FEATURE_REGIME:
            raise ValueError(
                f"Incompatible checkpoint feature regime: {state.get('model_feature_regime')} != {MODEL_FEATURE_REGIME}"
            )

        quantizer = AdaptiveQuantizer.from_state(state.get("quantizer", {}))
        model = IncrementalOBLMModel.from_state(state.get("model", {}))
        calibration = CalibrationTracker.from_state(state.get("calibration", {}))
        indicator_state = RollingIndicatorState.from_state(state.get("indicator_state", {}))
        pattern_tracker = SymbolicPatternTracker.from_state(state.get("pattern_tracker", {}))
        engine = cls(
            quantizer=quantizer,
            model=model,
            calibration=calibration,
            indicator_state=indicator_state,
            pattern_tracker=pattern_tracker,
            holding_minutes=int(state.get("holding_minutes", 5)),
            fuzzy_bias_weight=float(state.get("fuzzy_bias_weight", 0.25)),
            fuzzy_min_support_sequences=int(state.get("fuzzy_min_support_sequences", 3)),
            warmup_candles=int(state.get("warmup_candles", 10080)),
            enable_no_trade_gate=bool(state.get("enable_no_trade_gate", False)),
            no_trade_uncertainty_threshold=float(state.get("no_trade_uncertainty_threshold", 0.72)),
            trading_session_enabled=bool(state.get("trading_session_enabled", False)),
            trading_session_weekdays_only=bool(state.get("trading_session_weekdays_only", True)),
            trading_session_start_hour_utc=int(state.get("trading_session_start_hour_utc", 9)),
            trading_session_end_hour_utc=int(state.get("trading_session_end_hour_utc", 19)),
        )
        engine._candles_seen = int(state.get("candles_seen", 0))

        for raw in state.get("pending", []):
            engine._pending.append(
                PendingPrediction(
                    minute=datetime.fromisoformat(raw["minute"]),
                    token=str(raw["token"]),
                    model_input=str(raw.get("model_input") or _build_syllable_model_input(str(raw["token"]))),
                    reference_price=float(raw["reference_price"]),
                    predicted_direction=str(raw["predicted_direction"]),
                    bull_probability=float(raw["bull_probability"]),
                )
            )
        return engine


def _log_confidence_winrate_snapshot(
    confidence_logger: logging.Logger,
    tracker: ConfidenceWinrateTracker,
    minute: str,
    source: str,
    last_token: str,
    predicted_direction: str,
    cluster_winrate_pct: float,
    cluster_support: int,
    cluster_id: str,
    confidence_log_path: str,
    confidence_log_max_lines: int,
    min_total_for_log: int = 1
) -> None:
    # Compact runtime snapshot for the training bot:
    # one latest line with token + direction + tokenized-chain group winrate.
    _ = tracker  # kept for signature compatibility
    _ = source
    _ = cluster_support
    _ = cluster_id
    _ = minute
    _ = min_total_for_log
    confidence_logger.info(
        "token=%s predicted_direction=%s group_winrate=%.2f%%",
        str(last_token or "NA"),
        str(predicted_direction or "NA"),
        float(cluster_winrate_pct),
    )
    _trim_log_to_last_lines(
        log_path=confidence_log_path,
        max_lines=confidence_log_max_lines,
    )


def _log_symbolic_summary_snapshot(
    summary_logger: logging.Logger,
    minute: str,
    winloss_rows: list[dict[str, object]],
    gradient_rows: list[dict[str, object]],
    position_rows: list[dict[str, object]],
    bootstrap_status: dict[str, int],
    summary_log_path: str,
    summary_log_max_lines: int,
    min_total_for_log: int = 1,
    warmup_remaining: int = 0
) -> None:

    min_total = max(1, int(min_total_for_log))
    filtered_winloss_rows = [row for row in winloss_rows if int(row["total"]) >= min_total]
    filtered_position_rows = [row for row in position_rows if int(row["total"]) >= min_total]
    filtered_gradient_rows = [
        row
        for row in gradient_rows
        if (int(row.get("fragment_wins", 0)) + int(row.get("fragment_losses", 0))) >= min_total
    ]

    summary_logger.info("SYMBOLIC_SUMMARY minute=%s", minute)
    summary_logger.info("| Position | Feature | Label | Win Rate | Commonality |")
    summary_logger.info("| :--- | :--- | :--- | :--- | :--- |")
    if not filtered_winloss_rows:
        summary_logger.info(
            "| - | - | - | - | BOOTSTRAP: insufficient data (min_total=%d, left=%d, collected=%d/%d, snapshots_waiting=%d, warmup_left=%d) |",
            min_total,
            int(bootstrap_status.get("remaining", 0)),
            int(bootstrap_status.get("collected", 0)),
            int(bootstrap_status.get("needed", 25)),
            int(bootstrap_status.get("snapshots_waiting_settle", 0)),
            int(warmup_remaining),
        )
    for row in filtered_winloss_rows[:8]:
        position_label = _format_position_label(int(row["position"]), sequence_len=25)
        feature = str(row["feature"])
        label = str(row["label"])
        win_rate = float(row["winrate_pct"])
        commonality = str(row["commonality"])
        summary_logger.info(
            "| %s | %s | %s | %.2f%% | %s |",
            position_label,
            feature,
            label,
            win_rate,
            commonality,
        )

    summary_logger.info("WINRATE_BY_POSITION")
    summary_logger.info("| Position | Wins | Total | Win Rate | Commonality |")
    summary_logger.info("| :--- | :--- | :--- | :--- | :--- |")
    if not filtered_position_rows:
        summary_logger.info("| - | - | - | - | No settled position stats yet (or below min support) |")
    for row in filtered_position_rows[:8]:
        position_label = _format_position_label(int(row["position"]), sequence_len=25)
        summary_logger.info(
            "| %s | %d | %d | %.2f%% | %s |",
            position_label,
            int(row["wins"]),
            int(row["total"]),
            float(row["winrate_pct"]),
            str(row["commonality"]),
        )

    if not filtered_gradient_rows:
        summary_logger.info("NO_GRADIENT_ROWS yet (or below min support)")
    for row in filtered_gradient_rows[:8]:
        fragment = str(row["fragment"])
        win_freq = float(row["win_freq"])
        loss_freq = float(row["loss_freq"])
        delta = float(row["delta"])
        summary_logger.info(
            "%s %.2f %.2f %+0.2f (%s)",
            fragment,
            win_freq,
            loss_freq,
            delta,
            _gradient_strength_label(delta),
        )

    _trim_log_to_last_lines(
        log_path=summary_log_path,
        max_lines=summary_log_max_lines,
    )


async def run_oblm_training(
    symbol: str = "btcusdt",
    model_path: str = "data/oblm/model.pkl",
    save_interval_minutes: int = 1,
    rolling_window: int = 10080,
    warmup_candles: int = 30,
    holding_minutes: int = 5,
    fuzzy_bias_weight: float = 0.25,
    fuzzy_min_support_sequences: int = 3,
    enable_no_trade_gate: bool = False,
    no_trade_uncertainty_threshold: float = 0.72,
    trading_session_enabled: bool = False,
    trading_session_weekdays_only: bool = True,
    trading_session_start_hour_utc: int = 9,
    trading_session_end_hour_utc: int = 19,
    cluster_mode: str = "tree",
    cluster_rarity_z_threshold: float = 2.5,
    cluster_impact_weight_cap: float = 10.0,
    cluster_distance_threshold: float = 9.0,
    cluster_min_samples: int = 30,
    cluster_edge_winrate_threshold: float = 0.60,
    cluster_purity_split_winrate_threshold: float = 0.75,
    cluster_purity_split_min_support: int = 30,
    cluster_purity_split_tighten_factor: float = 0.60,
    cluster_purity_split_min_outliers: int = 1,
    cluster_tree_rebuild_interval: int = 25,
    cluster_tree_min_leaf_samples: int = 20,
    cluster_tree_max_depth: int = 4,
    cluster_tree_min_gain: float = 0.005,
    cluster_tree_history_cap: int = 5000,
    cluster_hdbscan_min_cluster_size: int = 20,
    cluster_hdbscan_min_samples: int = 10,
    cluster_hdbscan_rebuild_interval: int = 25,
    cluster_hdbscan_outcome_weight: float = 2.0,
    cluster_hdbscan_embedding_dim: int = 256,
    decision_log_path: str = "logs/oblm/decisions.log",
    decision_log_max_bytes: int = 2_000_000,
    decision_log_backup_count: int = 5,
    decision_log_max_lines: int = 100,
    confidence_log_path: str = "logs/oblm/confidence_winrate.log",
    confidence_log_max_bytes: int = 2_000_000,
    confidence_log_backup_count: int = 5,
    confidence_log_max_lines: int = 10,
    summary_log_path: str = "logs/oblm/symbolic_summary.log",
    summary_log_max_bytes: int = 2_000_000,
    summary_log_backup_count: int = 5,
    summary_log_max_lines: int = 200,
    min_total_for_log: int = 100,
    prefill_candles_path: str = "",
    prefill_limit: int = 10080,
) -> None:
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
    summary_logger = _configure_symbolic_summary_log_file(
        summary_log_path=summary_log_path,
        max_bytes=summary_log_max_bytes,
        backup_count=summary_log_backup_count,
    )
    confidence_tracker = ConfidenceWinrateTracker(rolling_window=10)
    _trim_log_to_last_lines(log_path=decision_log_path, max_lines=decision_log_max_lines)
    _trim_log_to_last_lines(log_path=summary_log_path, max_lines=summary_log_max_lines)

    checkpoint = Path(model_path)
    if checkpoint.exists():
        try:
            engine = OBLMEngine.load_from_file(checkpoint)
            # Runtime CLI/config values must override persisted checkpoint values.
            engine._holding_minutes = max(1, int(holding_minutes))
            engine._fuzzy_bias_weight = min(max(float(fuzzy_bias_weight), 0.0), 1.0)
            engine._fuzzy_min_support_sequences = max(1, int(fuzzy_min_support_sequences))
            engine._warmup_candles = max(0, int(warmup_candles))
            engine._enable_no_trade_gate = bool(enable_no_trade_gate)
            engine._no_trade_uncertainty_threshold = min(
                max(float(no_trade_uncertainty_threshold), 0.0),
                1.0,
            )
            engine._trading_session_enabled = bool(trading_session_enabled)
            engine._trading_session_weekdays_only = bool(trading_session_weekdays_only)
            engine._trading_session_start_hour_utc = int(trading_session_start_hour_utc) % 24
            engine._trading_session_end_hour_utc = int(trading_session_end_hour_utc) % 24
            requested_mode = str(cluster_mode or "tree").strip().lower()
            if requested_mode not in {"tree", "hdbscan"}:
                requested_mode = "tree"
            engine._pattern_tracker.cluster_mode_requested = requested_mode
            if requested_mode == "hdbscan" and not _SKLEARN_HDBSCAN_AVAILABLE:
                engine._pattern_tracker.cluster_mode_active = "tree"
            else:
                engine._pattern_tracker.cluster_mode_active = requested_mode
            engine._pattern_tracker.rarity_z_threshold = max(0.1, float(cluster_rarity_z_threshold))
            engine._pattern_tracker.impact_weight_cap = max(1.0, float(cluster_impact_weight_cap))
            engine._pattern_tracker.distance_threshold = max(0.1, float(cluster_distance_threshold))
            engine._pattern_tracker.min_cluster_samples = max(1, int(cluster_min_samples))
            engine._pattern_tracker.edge_winrate_threshold = min(
                max(float(cluster_edge_winrate_threshold), 0.50),
                0.99,
            )
            engine._pattern_tracker.purity_split_winrate_threshold = min(
                max(float(cluster_purity_split_winrate_threshold), 0.50),
                0.99,
            )
            engine._pattern_tracker.purity_split_min_support = max(1, int(cluster_purity_split_min_support))
            engine._pattern_tracker.purity_split_tighten_factor = min(
                max(float(cluster_purity_split_tighten_factor), 0.10),
                1.0,
            )
            engine._pattern_tracker.purity_split_min_outliers = max(1, int(cluster_purity_split_min_outliers))
            engine._pattern_tracker.tree_rebuild_interval = max(1, int(cluster_tree_rebuild_interval))
            engine._pattern_tracker.tree_min_leaf_samples = max(2, int(cluster_tree_min_leaf_samples))
            engine._pattern_tracker.tree_max_depth = max(1, int(cluster_tree_max_depth))
            engine._pattern_tracker.tree_min_gain = max(0.0, float(cluster_tree_min_gain))
            engine._pattern_tracker.tree_history_cap = max(100, int(cluster_tree_history_cap))
            engine._pattern_tracker.hdbscan_min_cluster_size = max(2, int(cluster_hdbscan_min_cluster_size))
            engine._pattern_tracker.hdbscan_min_samples = max(1, int(cluster_hdbscan_min_samples))
            engine._pattern_tracker.hdbscan_rebuild_interval = max(1, int(cluster_hdbscan_rebuild_interval))
            engine._pattern_tracker.hdbscan_outcome_weight = max(0.0, float(cluster_hdbscan_outcome_weight))
            engine._pattern_tracker.hdbscan_embedding_dim = max(32, int(cluster_hdbscan_embedding_dim))
            engine._last_warmup_remaining = max(0, engine._warmup_candles - int(engine._candles_seen))
            logger.info("Loaded existing OBLM model from %s", checkpoint)
        except Exception as exc:
            logger.warning("Failed to load checkpoint %s (%s). Starting fresh.", checkpoint, exc)
            engine = OBLMEngine(
                quantizer=AdaptiveQuantizer(rolling_window=rolling_window),
                indicator_state=RollingIndicatorState(rolling_window=rolling_window),
                holding_minutes=holding_minutes,
                fuzzy_bias_weight=fuzzy_bias_weight,
                fuzzy_min_support_sequences=fuzzy_min_support_sequences,
                warmup_candles=warmup_candles,
                enable_no_trade_gate=enable_no_trade_gate,
                no_trade_uncertainty_threshold=no_trade_uncertainty_threshold,
                trading_session_enabled=trading_session_enabled,
                trading_session_weekdays_only=trading_session_weekdays_only,
                trading_session_start_hour_utc=trading_session_start_hour_utc,
                trading_session_end_hour_utc=trading_session_end_hour_utc,
                cluster_mode=cluster_mode,
                cluster_rarity_z_threshold=cluster_rarity_z_threshold,
                cluster_impact_weight_cap=cluster_impact_weight_cap,
                cluster_distance_threshold=cluster_distance_threshold,
                cluster_min_samples=cluster_min_samples,
                cluster_edge_winrate_threshold=cluster_edge_winrate_threshold,
                cluster_purity_split_winrate_threshold=cluster_purity_split_winrate_threshold,
                cluster_purity_split_min_support=cluster_purity_split_min_support,
                cluster_purity_split_tighten_factor=cluster_purity_split_tighten_factor,
                cluster_purity_split_min_outliers=cluster_purity_split_min_outliers,
                cluster_tree_rebuild_interval=cluster_tree_rebuild_interval,
                cluster_tree_min_leaf_samples=cluster_tree_min_leaf_samples,
                cluster_tree_max_depth=cluster_tree_max_depth,
                cluster_tree_min_gain=cluster_tree_min_gain,
                cluster_tree_history_cap=cluster_tree_history_cap,
                cluster_hdbscan_min_cluster_size=cluster_hdbscan_min_cluster_size,
                cluster_hdbscan_min_samples=cluster_hdbscan_min_samples,
                cluster_hdbscan_rebuild_interval=cluster_hdbscan_rebuild_interval,
                cluster_hdbscan_outcome_weight=cluster_hdbscan_outcome_weight,
                cluster_hdbscan_embedding_dim=cluster_hdbscan_embedding_dim,
            )
    else:
        engine = OBLMEngine(
            quantizer=AdaptiveQuantizer(rolling_window=rolling_window),
            indicator_state=RollingIndicatorState(rolling_window=rolling_window),
            holding_minutes=holding_minutes,
            fuzzy_bias_weight=fuzzy_bias_weight,
            fuzzy_min_support_sequences=fuzzy_min_support_sequences,
            warmup_candles=warmup_candles,
            enable_no_trade_gate=enable_no_trade_gate,
            no_trade_uncertainty_threshold=no_trade_uncertainty_threshold,
            trading_session_enabled=trading_session_enabled,
            trading_session_weekdays_only=trading_session_weekdays_only,
            trading_session_start_hour_utc=trading_session_start_hour_utc,
            trading_session_end_hour_utc=trading_session_end_hour_utc,
            cluster_mode=cluster_mode,
            cluster_rarity_z_threshold=cluster_rarity_z_threshold,
            cluster_impact_weight_cap=cluster_impact_weight_cap,
            cluster_distance_threshold=cluster_distance_threshold,
            cluster_min_samples=cluster_min_samples,
            cluster_edge_winrate_threshold=cluster_edge_winrate_threshold,
            cluster_purity_split_winrate_threshold=cluster_purity_split_winrate_threshold,
            cluster_purity_split_min_support=cluster_purity_split_min_support,
            cluster_purity_split_tighten_factor=cluster_purity_split_tighten_factor,
            cluster_purity_split_min_outliers=cluster_purity_split_min_outliers,
            cluster_tree_rebuild_interval=cluster_tree_rebuild_interval,
            cluster_tree_min_leaf_samples=cluster_tree_min_leaf_samples,
            cluster_tree_max_depth=cluster_tree_max_depth,
            cluster_tree_min_gain=cluster_tree_min_gain,
            cluster_tree_history_cap=cluster_tree_history_cap,
            cluster_hdbscan_min_cluster_size=cluster_hdbscan_min_cluster_size,
            cluster_hdbscan_min_samples=cluster_hdbscan_min_samples,
            cluster_hdbscan_rebuild_interval=cluster_hdbscan_rebuild_interval,
            cluster_hdbscan_outcome_weight=cluster_hdbscan_outcome_weight,
            cluster_hdbscan_embedding_dim=cluster_hdbscan_embedding_dim,
        )

    if prefill_candles_path:
        try:
            prefill = _load_prefill_candles(path=prefill_candles_path, limit=prefill_limit)
            for candle in prefill:
                synthetic_price = float(candle.close)
                synthetic_state = MarketState(
                    timestamp=_minute_floor(candle.timestamp),
                    l2=L2Snapshot(
                        timestamp=_minute_floor(candle.timestamp),
                        bids=[(synthetic_price * 0.9995, 1.0), (synthetic_price * 0.9990, 1.0)],
                        asks=[(synthetic_price * 1.0005, 1.0), (synthetic_price * 1.0010, 1.0)],
                    ),
                    candle=candle,
                )
                # Warmup-only prefill: build indicator/quantization context and symbolic rolling window
                # without generating pending predictions or learning outcomes from synthetic history.
                engine._candles_seen += 1
                indicator_context = engine._indicator_state.update(candle)
                token = engine._quantizer.to_token(state=synthetic_state, indicator_context=indicator_context)
                engine._last_indicator_context = dict(indicator_context)
                engine._last_token = token
                engine._last_model_input = _build_syllable_model_input(token, include_interactions=True)
                engine._pattern_tracker.observe_token(token)

            if prefill:
                baseline_missing = max(0, int(rolling_window) - len(prefill))
                logger.info(
                    "Applied prefill warmup from %s: candles=%d first=%s last=%s baseline_missing=%d",
                    prefill_candles_path,
                    len(prefill),
                    _minute_floor(prefill[0].timestamp).isoformat(),
                    _minute_floor(prefill[-1].timestamp).isoformat(),
                    baseline_missing,
                )
            else:
                logger.warning("Prefill file loaded but produced 0 candles: %s", prefill_candles_path)
        except Exception as exc:
            logger.warning("Failed prefill from %s (%s). Continuing without prefill.", prefill_candles_path, exc)

    startup_minute = _minute_floor(datetime.now(timezone.utc)).isoformat()
    decision_logger.info(
        "STARTUP minute=%s symbol=%s warmup_candles=%d warmup_left=%d rolling_window=%d prefill_path=%s",
        startup_minute,
        symbol,
        int(warmup_candles),
        int(engine.warmup_remaining),
        int(rolling_window),
        prefill_candles_path or "NONE",
    )
    decision_logger.info(
        "WAITING_MARKET_DATA minute=%s pending=%d token=%s",
        startup_minute,
        engine.pending_count,
        engine.last_token or "NA",
    )
    _trim_log_to_last_lines(log_path=decision_log_path, max_lines=decision_log_max_lines)

    startup_winloss_rows, startup_gradient_rows = engine.symbolic_summary_rows()
    _log_symbolic_summary_snapshot(
        summary_logger=summary_logger,
        minute=startup_minute,
        winloss_rows=startup_winloss_rows,
        gradient_rows=startup_gradient_rows,
        position_rows=engine.symbolic_position_rows(),
        bootstrap_status=engine.symbolic_bootstrap_status(),
        summary_log_path=summary_log_path,
        summary_log_max_lines=summary_log_max_lines,
        min_total_for_log=min_total_for_log,
        warmup_remaining=engine.warmup_remaining,
    )

    async def on_market_state(state: MarketState) -> None:
        output = engine.process_market_state(state)
        move = "HOLD" if output.action == "NO_TRADE" else ("UP" if output.direction == "BULL" else "DOWN")
        probability_pct = output.probability * 100.0
        indicator_context = engine.last_indicator_context
        avg_volume_1m_7d = indicator_context.get("avg_volume_1m_7d")
        volume_2h_vs_avg = float(indicator_context.get("volume_2h_vs_avg", 1.0) or 1.0)

        decision_logger.info(
            "CONTEXT minute=%s rolling_window=%d avg_volume_1m_7d=%s volume_2h_vs_avg=%.6f",
            output.timestamp,
            int(rolling_window),
            "NA" if avg_volume_1m_7d is None else f"{float(avg_volume_1m_7d):.6f}",
            volume_2h_vs_avg,
        )

        decision_logger.info(
            "DECISION minute=%s move=%s action=%s probability=%.2f%% uncertainty=%.3f reason=%s warmup_left=%d token=%s model_input=%s warmed_up=%s",
            output.timestamp,
            move,
            output.action,
            probability_pct,
            float(output.uncertainty),
            output.reason,
            int(engine.warmup_remaining),
            engine.last_token or "NA",
            " ".join((engine.last_model_input or "NA").split(" ")[:8]),
            engine.warmed_up,
        )
        direction_label = _position_direction_label(output.direction)
        decision_logger.info(
            "DIRECTION minute=%s predicted_direction=%s",
            output.timestamp,
            direction_label,
        )
        cluster_signal = engine.last_cluster_signal
        decision_logger.info(
            "CLUSTER_SIGNAL minute=%s direction=%s cluster_id=%s support=%d winrate=%.2f%% qualified=%s distance=%s reason=%s source=%s tree_path=%s tree_gain=%.4f",
            output.timestamp,
            str(cluster_signal.get("direction", "NA")),
            str(cluster_signal.get("cluster_id", "NA")),
            int(cluster_signal.get("support", 0)),
            float(cluster_signal.get("winrate_pct", 0.0)),
            bool(cluster_signal.get("qualified", False)),
            "NA" if cluster_signal.get("distance") is None else f"{float(cluster_signal.get('distance', 0.0)):.4f}",
            str(cluster_signal.get("reason", "na")),
            str(cluster_signal.get("source", "cluster")),
            str(cluster_signal.get("tree_path", "NA")),
            float(cluster_signal.get("tree_gain_sum", 0.0)),
        )
        fuzzy = engine.last_fuzzy_bias
        top_pos = ",".join(
            f"{str(row.get('fragment'))}:{float(row.get('delta', 0.0)):+.2f}"
            for row in (fuzzy.get("top_positive", []) or [])[:3]
        ) or "NA"
        top_neg = ",".join(
            f"{str(row.get('fragment'))}:{float(row.get('delta', 0.0)):+.2f}"
            for row in (fuzzy.get("top_negative", []) or [])[:3]
        ) or "NA"
        decision_logger.info(
            "FUZZY_BIAS minute=%s score=%.4f signal=%s matched=%d support_sum=%d weight=%.3f min_support=%d reason=%s top_pos=%s top_neg=%s",
            output.timestamp,
            float(fuzzy.get("score", 0.0)),
            str(fuzzy.get("signal", "Neutral")),
            int(fuzzy.get("matched", 0)),
            int(fuzzy.get("support_sum", 0)),
            float(engine._fuzzy_bias_weight),
            int(engine._fuzzy_min_support_sequences),
            str(fuzzy.get("reason", "na")),
            top_pos,
            top_neg,
        )

        has_new_settlement = False
        latest_winloss_rows: list[dict[str, object]] = []
        latest_gradient_rows: list[dict[str, object]] = []
        for settled in engine.last_settlements:
            has_new_settlement = True
            confidence_tracker.update(
                confidence=float(settled["confidence"]),
                correct=bool(settled["correct"]),
                vol2h_bucket=str(settled.get("vol2h_bucket", "NA")),
            )
            decision_logger.info(
                "SETTLE pred_minute=%s predicted=%s predicted_direction=%s realized=%s correct=%s confidence=%.3f exit=%.4f reason=%s age_minutes=%d sequence_mode=%s sequence_len=%d",
                settled["pred_minute"],
                settled["predicted"],
                _position_direction_label(str(settled["predicted"])),
                settled["realized"],
                settled["correct"],
                float(settled["confidence"]),
                float(settled["exit_price"]),
                str(settled["settle_reason"]),
                int(settled["age_minutes"]),
                str(settled.get("sequence_mode", "na")),
                int(settled.get("sequence_len", 0)),
            )
            cluster = settled.get("cluster", {}) if isinstance(settled.get("cluster"), dict) else {}
            decision_logger.info(
                "SETTLE_CLUSTER pred_minute=%s cluster_id=%s direction=%s support=%d wins=%d losses=%d winrate=%.2f%% qualified=%s distance=%s source=%s tree_leaf_id=%s tree_support=%s tree_winrate=%s tree_path=%s",
                settled["pred_minute"],
                str(cluster.get("cluster_id", "NA")),
                str(cluster.get("direction", "NA")),
                int(cluster.get("support", 0)),
                int(cluster.get("wins", 0)),
                int(cluster.get("losses", 0)),
                float(cluster.get("winrate_pct", 0.0)),
                bool(cluster.get("qualified", False)),
                "NA" if cluster.get("distance") is None else f"{float(cluster.get('distance', 0.0)):.4f}",
                str(cluster.get("source", "cluster")),
                str(cluster.get("tree_leaf_id", "NA")),
                str(cluster.get("tree_support", "NA")),
                str(cluster.get("tree_winrate_pct", "NA")),
                str(cluster.get("tree_path", "NA")),
            )

            winloss_rows = settled.get("winloss_rows", [])
            decision_logger.info("WINLOSS_TABLE minute=%s rows=%d", output.timestamp, len(winloss_rows))
            for row in winloss_rows[:15]:
                decision_logger.info(
                    "WINLOSS_ROW position=%d feature=%s label=%s wins=%d total=%d winrate=%.2f%% commonality=%s",
                    int(row["position"]),
                    row["feature"],
                    row["label"],
                    int(row["wins"]),
                    int(row["total"]),
                    float(row["winrate_pct"]),
                    row["commonality"],
                )

            gradient_rows = settled.get("gradient_rows", [])
            decision_logger.info("GRADIENT_TABLE minute=%s rows=%d", output.timestamp, len(gradient_rows))
            for row in gradient_rows[:15]:
                decision_logger.info(
                    "GRADIENT_ROW fragment=%s win_freq=%.4f loss_freq=%.4f delta=%.4f signal=%s",
                    row["fragment"],
                    float(row["win_freq"]),
                    float(row["loss_freq"]),
                    float(row["delta"]),
                    row["signal"],
                )

            ngram_rows = settled.get("ngram_rows", [])
            decision_logger.info("NGRAM_TABLE minute=%s rows=%d", output.timestamp, len(ngram_rows))
            for row in ngram_rows[:15]:
                decision_logger.info(
                    "NGRAM_ROW support=%d win_freq=%.4f loss_freq=%.4f win_rate=%.4f pattern=%s",
                    int(row["support"]),
                    float(row["win_freq"]),
                    float(row["loss_freq"]),
                    float(row["win_rate"]),
                    row["pattern"],
                )
            latest_winloss_rows = winloss_rows
            latest_gradient_rows = gradient_rows

        if not has_new_settlement:
            latest_winloss_rows, latest_gradient_rows = engine.symbolic_summary_rows()
        latest_position_rows = engine.symbolic_position_rows()

        _log_symbolic_summary_snapshot(
            summary_logger=summary_logger,
            minute=output.timestamp,
            winloss_rows=latest_winloss_rows,
            gradient_rows=latest_gradient_rows,
            position_rows=latest_position_rows,
            bootstrap_status=engine.symbolic_bootstrap_status(),
            summary_log_path=summary_log_path,
            summary_log_max_lines=summary_log_max_lines,
            min_total_for_log=min_total_for_log,
            warmup_remaining=engine.warmup_remaining,
        )

        if has_new_settlement:
            _log_confidence_winrate_snapshot(
                confidence_logger=confidence_logger,
                tracker=confidence_tracker,
                minute=output.timestamp,
                source="settlement",
                last_token=str(engine.last_token or "NA"),
                predicted_direction=_position_direction_label(output.direction),
                cluster_winrate_pct=float(engine.last_cluster_signal.get("winrate_pct", 0.0)),
                cluster_support=int(engine.last_cluster_signal.get("support", 0)),
                cluster_id=str(engine.last_cluster_signal.get("cluster_id", "NA")),
                confidence_log_path=confidence_log_path,
                confidence_log_max_lines=confidence_log_max_lines,
                min_total_for_log=min_total_for_log,
            )

        calibration = engine.calibration_summary()
        decision_logger.info(
            "STATUS minute=%s pending=%d cal_samples=%d cal_ece=%.6f holding_minutes=%d",
            output.timestamp,
            engine.pending_count,
            int(calibration.get("samples", 0)),
            float(calibration.get("ece", 0.0)),
            int(holding_minutes),
        )
        _trim_log_to_last_lines(log_path=decision_log_path, max_lines=decision_log_max_lines)

    pipeline = BinanceMarketDataPipeline(
        symbol=symbol,
        on_market_state=on_market_state,
    )
    stop_event = asyncio.Event()

    async def periodic_save() -> None:
        while not stop_event.is_set():
            await asyncio.sleep(max(1, save_interval_minutes) * 60)
            engine.save_to_file(checkpoint)
            now_minute = _minute_floor(datetime.now(timezone.utc)).isoformat()
            decision_logger.info(
                "HEARTBEAT minute=%s pending=%d warmup_left=%d warmed_up=%s token=%s",
                now_minute,
                engine.pending_count,
                int(engine.warmup_remaining),
                engine.warmed_up,
                engine.last_token or "NA",
            )
            _trim_log_to_last_lines(log_path=decision_log_path, max_lines=decision_log_max_lines)

            hb_winloss_rows, hb_gradient_rows = engine.symbolic_summary_rows()
            _log_symbolic_summary_snapshot(
                summary_logger=summary_logger,
                minute=now_minute,
                winloss_rows=hb_winloss_rows,
                gradient_rows=hb_gradient_rows,
                position_rows=engine.symbolic_position_rows(),
                bootstrap_status=engine.symbolic_bootstrap_status(),
                summary_log_path=summary_log_path,
                summary_log_max_lines=summary_log_max_lines,
                min_total_for_log=min_total_for_log,
                warmup_remaining=engine.warmup_remaining,
            )
            _log_confidence_winrate_snapshot(
                confidence_logger=confidence_logger,
                tracker=confidence_tracker,
                minute=now_minute,
                source="heartbeat",
                last_token=str(engine.last_token or "NA"),
                predicted_direction=str(engine.last_cluster_signal.get("direction", "NA")),
                cluster_winrate_pct=float(engine.last_cluster_signal.get("winrate_pct", 0.0)),
                cluster_support=int(engine.last_cluster_signal.get("support", 0)),
                cluster_id=str(engine.last_cluster_signal.get("cluster_id", "NA")),
                confidence_log_path=confidence_log_path,
                confidence_log_max_lines=confidence_log_max_lines,
                min_total_for_log=min_total_for_log,
            )

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            pass

    saver = asyncio.create_task(periodic_save())
    await pipeline.start()

    try:
        await stop_event.wait()
    finally:
        await pipeline.stop()
        saver.cancel()
        try:
            await saver
        except asyncio.CancelledError:
            pass
        engine.save_to_file(checkpoint)
        _log_confidence_winrate_snapshot(
            confidence_logger=confidence_logger,
            tracker=confidence_tracker,
            minute=_minute_floor(datetime.now(timezone.utc)).isoformat(),
            source="shutdown",
            last_token=str(engine.last_token or "NA"),
            predicted_direction=str(engine.last_cluster_signal.get("direction", "NA")),
            cluster_winrate_pct=float(engine.last_cluster_signal.get("winrate_pct", 0.0)),
            cluster_support=int(engine.last_cluster_signal.get("support", 0)),
            cluster_id=str(engine.last_cluster_signal.get("cluster_id", "NA")),
            confidence_log_path=confidence_log_path,
            confidence_log_max_lines=confidence_log_max_lines,
            min_total_for_log=min_total_for_log,
        )


class BinanceMarketDataPipeline:
    def __init__(
        self,
        symbol: str,
        on_market_state: Callable[[MarketState], Awaitable[None]],
        depth_levels: int = 20,
        ws_base_url: str = "wss://stream.binance.com:9443/ws",
    ):
        self._symbol = symbol.lower()
        self._on_market_state = on_market_state
        self._depth_levels = depth_levels
        self._ws_base = ws_base_url.rstrip("/")
        self._sync = MinuteMarketStateSynchronizer()
        self._running = False
        self._tasks: list[asyncio.Task] = []

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
            raise RuntimeError("websockets package is required for live OBLM pipeline")
        backoff = 1.0
        while self._running:
            try:
                async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
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
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2.0, 30.0)

    async def _handle_depth_message(self, message: dict) -> None:
        raw_bids = message.get("b") or message.get("bids") or []
        raw_asks = message.get("a") or message.get("asks") or []
        bids = [(float(p), float(q)) for p, q in raw_bids][: self._depth_levels]
        asks = [(float(p), float(q)) for p, q in raw_asks][: self._depth_levels]

        event_ms = int(message.get("E", 0))
        depth_ts = _utc_from_ms(event_ms) if event_ms > 0 else datetime.now(timezone.utc)
        state = self._sync.add_l2(L2Snapshot(timestamp=depth_ts, bids=bids, asks=asks))
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
    def _parse_bool(value: str) -> bool:
        text = str(value).strip().lower()
        if text in {"1", "true", "t", "yes", "y", "on"}:
            return True
        if text in {"0", "false", "f", "no", "n", "off"}:
            return False
        raise argparse.ArgumentTypeError(f"Invalid boolean value: {value}")

    parser = argparse.ArgumentParser(description="Run OBLM v2 symbolic strategy loop")
    parser.add_argument("--symbol", default="btcusdt", help="Binance symbol")
    parser.add_argument("--model-path", default="data/oblm/model.pkl", help="Path to OBLM checkpoint file")
    parser.add_argument("--save-interval-minutes", type=int, default=1, help="Checkpoint save interval in minutes")
    parser.add_argument(
        "--rolling-window",
        type=int,
        default=10080,
        help="Rolling window size (default 7 days of 1m candles)",
    )
    parser.add_argument(
        "--warmup-candles",
        type=int,
        default=30,
        help="Warmup candles before full-confidence operation",
    )
    parser.add_argument(
        "--holding-minutes",
        type=int,
        default=5,
        help="Settle prediction exactly after N minutes from entry",
    )
    parser.add_argument(
        "--fuzzy-bias-weight",
        type=float,
        default=0.25,
        help="Weight applied to fuzzy gradient score when adjusting bull probability",
    )
    parser.add_argument(
        "--fuzzy-min-support-sequences",
        type=int,
        default=3,
        help="Minimum settled sequence support for fragment to be used in fuzzy bias",
    )
    parser.add_argument(
        "--enable-no-trade-gate",
        action="store_true",
        help="Enable NO_TRADE action when uncertainty is high",
    )
    parser.add_argument(
        "--no-trade-uncertainty-threshold",
        type=float,
        default=0.72,
        help="Uncertainty threshold above which action becomes NO_TRADE",
    )
    parser.add_argument(
        "--trading-session-enabled",
        type=_parse_bool,
        default=False,
        help="Enable trading-session gate (false allows 24/7 trading)",
    )
    parser.add_argument(
        "--trading-session-weekdays-only",
        type=_parse_bool,
        default=True,
        help="When session gate is enabled, restrict trades to Mon-Fri",
    )
    parser.add_argument(
        "--trading-session-start-hour-utc",
        type=int,
        default=9,
        help="When session gate is enabled, inclusive UTC start hour (0-23)",
    )
    parser.add_argument(
        "--trading-session-end-hour-utc",
        type=int,
        default=19,
        help="When session gate is enabled, exclusive UTC end hour (0-23)",
    )
    parser.add_argument(
        "--cluster-mode",
        default="tree",
        choices=["tree", "hdbscan"],
        help="Cluster discovery mode: divisive tree (entropy gain) or HDBSCAN density mode",
    )
    parser.add_argument(
        "--cluster-rarity-z-threshold",
        type=float,
        default=2.5,
        help="Absolute z-score threshold for high-impact token@position rarity",
    )
    parser.add_argument(
        "--cluster-impact-weight-cap",
        type=float,
        default=10.0,
        help="Maximum rarity weight used in weighted chain distance",
    )
    parser.add_argument(
        "--cluster-distance-threshold",
        type=float,
        default=9.0,
        help="Maximum weighted distance to assign chain to existing cluster",
    )
    parser.add_argument(
        "--cluster-min-samples",
        type=int,
        default=30,
        help="Minimum cluster samples required before cluster is treated as statistically qualified",
    )
    parser.add_argument(
        "--cluster-edge-winrate-threshold",
        type=float,
        default=0.60,
        help="Qualified cluster requires winrate >= threshold or <= (1-threshold)",
    )
    parser.add_argument(
        "--cluster-purity-split-winrate-threshold",
        type=float,
        default=0.75,
        help="When nearest cluster winrate is above this (with enough support), tighten join threshold",
    )
    parser.add_argument(
        "--cluster-purity-split-min-support",
        type=int,
        default=30,
        help="Minimum cluster support required before purity split logic is active",
    )
    parser.add_argument(
        "--cluster-purity-split-tighten-factor",
        type=float,
        default=0.60,
        help="Multiplier applied to distance threshold for high-win clusters (lower = stricter)",
    )
    parser.add_argument(
        "--cluster-purity-split-min-outliers",
        type=int,
        default=1,
        help="Minimum high-impact outlier token@position pairs required to force purity split",
    )
    parser.add_argument(
        "--cluster-tree-rebuild-interval",
        type=int,
        default=25,
        help="Rebuild interval (in settled samples) for divisive tree mode",
    )
    parser.add_argument(
        "--cluster-tree-min-leaf-samples",
        type=int,
        default=20,
        help="Minimum samples required per branch leaf in divisive tree mode",
    )
    parser.add_argument(
        "--cluster-tree-max-depth",
        type=int,
        default=4,
        help="Maximum recursive split depth for divisive tree mode",
    )
    parser.add_argument(
        "--cluster-tree-min-gain",
        type=float,
        default=0.005,
        help="Minimum entropy gain required to keep a divisive split",
    )
    parser.add_argument(
        "--cluster-tree-history-cap",
        type=int,
        default=5000,
        help="Maximum settled chains retained per direction for tree/HDBSCAN rebuild",
    )
    parser.add_argument(
        "--cluster-hdbscan-min-cluster-size",
        type=int,
        default=20,
        help="HDBSCAN minimum cluster size",
    )
    parser.add_argument(
        "--cluster-hdbscan-min-samples",
        type=int,
        default=10,
        help="HDBSCAN min_samples value",
    )
    parser.add_argument(
        "--cluster-hdbscan-rebuild-interval",
        type=int,
        default=25,
        help="Rebuild interval (in settled samples) for HDBSCAN mode",
    )
    parser.add_argument(
        "--cluster-hdbscan-outcome-weight",
        type=float,
        default=2.0,
        help="Weight for outcome (+1/-1) dimension in HDBSCAN embedding",
    )
    parser.add_argument(
        "--cluster-hdbscan-embedding-dim",
        type=int,
        default=256,
        help="Hashed embedding dimensionality for HDBSCAN clustering",
    )
    parser.add_argument("--decision-log-path", default="logs/oblm/decisions.log", help="Decision log path")
    parser.add_argument("--decision-log-max-bytes", type=int, default=2_000_000, help="Decision log max bytes")
    parser.add_argument("--decision-log-backup-count", type=int, default=5, help="Decision log backups")
    parser.add_argument("--decision-log-max-lines", type=int, default=100, help="Decision log tail lines")
    parser.add_argument("--confidence-log-path", default="logs/oblm/confidence_winrate.log", help="Confidence log path")
    parser.add_argument("--confidence-log-max-bytes", type=int, default=2_000_000, help="Confidence log max bytes")
    parser.add_argument("--confidence-log-backup-count", type=int, default=5, help="Confidence log backups")
    parser.add_argument("--confidence-log-max-lines", type=int, default=10, help="Confidence log tail lines")
    parser.add_argument("--summary-log-path", default="logs/oblm/symbolic_summary.log", help="Symbolic summary log path")
    parser.add_argument("--summary-log-max-bytes", type=int, default=2_000_000, help="Symbolic summary log max bytes")
    parser.add_argument("--summary-log-backup-count", type=int, default=5, help="Symbolic summary log backups")
    parser.add_argument("--summary-log-max-lines", type=int, default=200, help="Symbolic summary log tail lines")
    parser.add_argument(
        "--min-total-for-log",
        type=int,
        default=100,
        help="Minimum support total required before logging detailed rows",
    )
    parser.add_argument(
        "--prefill-candles-path",
        default="",
        help="Path to Freqtrade 1m candle export (JSON/CSV) used for startup warmup",
    )
    parser.add_argument(
        "--prefill-limit",
        type=int,
        default=10080,
        help="Maximum number of candles loaded from prefill source",
    )
    return parser.parse_args()


def _setup_default_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def main() -> None:
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    _setup_default_logging()
    args = _parse_oblm_args()
    asyncio.run(
        run_oblm_training(
            symbol=args.symbol,
            model_path=args.model_path,
            save_interval_minutes=args.save_interval_minutes,
            rolling_window=args.rolling_window,
            warmup_candles=args.warmup_candles,
            holding_minutes=args.holding_minutes,
            fuzzy_bias_weight=args.fuzzy_bias_weight,
            fuzzy_min_support_sequences=args.fuzzy_min_support_sequences,
            enable_no_trade_gate=args.enable_no_trade_gate,
            no_trade_uncertainty_threshold=args.no_trade_uncertainty_threshold,
            trading_session_enabled=args.trading_session_enabled,
            trading_session_weekdays_only=args.trading_session_weekdays_only,
            trading_session_start_hour_utc=args.trading_session_start_hour_utc,
            trading_session_end_hour_utc=args.trading_session_end_hour_utc,
            cluster_mode=args.cluster_mode,
            cluster_rarity_z_threshold=args.cluster_rarity_z_threshold,
            cluster_impact_weight_cap=args.cluster_impact_weight_cap,
            cluster_distance_threshold=args.cluster_distance_threshold,
            cluster_min_samples=args.cluster_min_samples,
            cluster_edge_winrate_threshold=args.cluster_edge_winrate_threshold,
            cluster_purity_split_winrate_threshold=args.cluster_purity_split_winrate_threshold,
            cluster_purity_split_min_support=args.cluster_purity_split_min_support,
            cluster_purity_split_tighten_factor=args.cluster_purity_split_tighten_factor,
            cluster_purity_split_min_outliers=args.cluster_purity_split_min_outliers,
            cluster_tree_rebuild_interval=args.cluster_tree_rebuild_interval,
            cluster_tree_min_leaf_samples=args.cluster_tree_min_leaf_samples,
            cluster_tree_max_depth=args.cluster_tree_max_depth,
            cluster_tree_min_gain=args.cluster_tree_min_gain,
            cluster_tree_history_cap=args.cluster_tree_history_cap,
            cluster_hdbscan_min_cluster_size=args.cluster_hdbscan_min_cluster_size,
            cluster_hdbscan_min_samples=args.cluster_hdbscan_min_samples,
            cluster_hdbscan_rebuild_interval=args.cluster_hdbscan_rebuild_interval,
            cluster_hdbscan_outcome_weight=args.cluster_hdbscan_outcome_weight,
            cluster_hdbscan_embedding_dim=args.cluster_hdbscan_embedding_dim,
            decision_log_path=args.decision_log_path,
            decision_log_max_bytes=args.decision_log_max_bytes,
            decision_log_backup_count=args.decision_log_backup_count,
            decision_log_max_lines=args.decision_log_max_lines,
            confidence_log_path=args.confidence_log_path,
            confidence_log_max_bytes=args.confidence_log_max_bytes,
            confidence_log_backup_count=args.confidence_log_backup_count,
            confidence_log_max_lines=args.confidence_log_max_lines,
            summary_log_path=args.summary_log_path,
            summary_log_max_bytes=args.summary_log_max_bytes,
            summary_log_backup_count=args.summary_log_backup_count,
            summary_log_max_lines=args.summary_log_max_lines,
            min_total_for_log=args.min_total_for_log,
            prefill_candles_path=args.prefill_candles_path,
            prefill_limit=args.prefill_limit,
        )
    )


if __name__ == "__main__":
    main()
