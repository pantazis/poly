"""Similar-state empirical memory layer for OBLM.

This module adds a persistent, regime-aware memory over live predictions.
It tracks prediction-time state, then updates records on settlement and exposes
empirical winrate estimates for similar historical states.

Minimal usage example:

    memory = SimilarStateMemory(
        sqlite_path="data/oblm/memory.db",
        k_neighbors=84,
        bayes_alpha=10.0,
        bayes_beta=10.0,
    )

    prediction_id = memory.insert_prediction(
        timestamp="2026-04-01T06:30:00+00:00",
        symbol="btcusdt",
        token="IMB_HIGH_SPD_NORM_DPT_MID_BOD_LONG_WCK_LOW_VOL_HIGH_CNDL_BULL",
        feature_vector=[0.2, 0.01, 14.0, 0.004, 1.8, 1.3],
        predicted_direction="LONG",
        model_confidence=0.91,
        regimes={"volume": "HIGH", "spread": "NORM", "depth": "MID"},
        reference_price=70000.0,
        settlement_horizon_minutes=5,
    )

    memory.settle_prediction(
        prediction_id=prediction_id,
        settled_at="2026-04-01T06:35:00+00:00",
        realized_direction="LONG",
        eval_price=70080.0,
    )

    lookup = memory.lookup_similar(
        symbol="btcusdt",
        token="IMB_HIGH_SPD_NORM_DPT_MID_BOD_LONG_WCK_LOW_VOL_HIGH_CNDL_BULL",
        feature_vector=[0.2, 0.01, 14.0, 0.004, 1.8, 1.3],
        predicted_direction="LONG",
        regimes={"volume": "HIGH"},
    )

    # lookup.smoothed_memory_winrate is empirical and prior-smoothed.
"""

from __future__ import annotations

import json
import logging
import math
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


def _utc_iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_iso(ts: datetime | str) -> str:
    if isinstance(ts, str):
        return ts
    return ts.isoformat()


def _safe_float(value: float, fallback: float = 0.0) -> float:
    if not math.isfinite(value):
        return fallback
    return float(value)


def _euclidean_distance(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return float("inf")
    n = min(len(a), len(b))
    if n == 0:
        return float("inf")
    acc = 0.0
    for i in range(n):
        diff = a[i] - b[i]
        acc += diff * diff
    return math.sqrt(acc)


def _token_jaccard(a: str, b: str) -> float:
    set_a = {p for p in a.split("_") if p}
    set_b = {p for p in b.split("_") if p}
    if not set_a or not set_b:
        return 0.0
    inter = len(set_a.intersection(set_b))
    union = len(set_a.union(set_b))
    if union == 0:
        return 0.0
    return inter / union


@dataclass(frozen=True)
class MemoryLookupResult:
    memory_winrate: float
    smoothed_memory_winrate: float
    memory_samples: int
    regime_filtered_samples: int
    last_5_winrate: float
    last_5_samples: int
    match_method: str


@dataclass(frozen=True)
class TradeVerdict:
    verdict: str
    reason: str


class MemoryDecisionGate:
    """Simple helper to combine model confidence and empirical memory edge."""

    def __init__(
        self,
        min_samples_to_trust: int = 30,
        min_smoothed_winrate: float = 0.55,
        min_memory_winrate: float = 0.80,
        min_last_5_winrate: float = 1.0,
        tradable_volume_regimes: tuple[str, ...] = ("MID", "HIGH"),
    ):
        self._min_samples_to_trust = max(1, int(min_samples_to_trust))
        self._min_smoothed_winrate = float(min_smoothed_winrate)
        self._min_memory_winrate = float(min_memory_winrate)
        self._min_last_5_winrate = float(min_last_5_winrate)
        self._tradable_volume_regimes = set(tradable_volume_regimes)

    def evaluate(
        self,
        model_confidence: float,
        lookup: MemoryLookupResult,
        volume_regime: str,
    ) -> TradeVerdict:
        if volume_regime not in self._tradable_volume_regimes:
            return TradeVerdict("SKIP", f"non_tradable_volume_regime={volume_regime}")
        if lookup.memory_samples < self._min_samples_to_trust:
            return TradeVerdict(
                "SKIP",
                f"insufficient_memory_samples={lookup.memory_samples}",
            )
        if lookup.smoothed_memory_winrate < self._min_smoothed_winrate:
            return TradeVerdict(
                "SKIP",
                f"smoothed_memory_winrate_below_threshold={lookup.smoothed_memory_winrate:.3f}",
            )
        if lookup.memory_winrate < self._min_memory_winrate:
            return TradeVerdict(
                "SKIP",
                f"memory_winrate_below_threshold={lookup.memory_winrate:.3f}",
            )
        if lookup.last_5_samples < 5:
            return TradeVerdict(
                "SKIP",
                f"insufficient_last_5_samples={lookup.last_5_samples}",
            )
        if lookup.last_5_winrate < self._min_last_5_winrate:
            return TradeVerdict(
                "SKIP",
                f"last_5_winrate_below_threshold={lookup.last_5_winrate:.3f}",
            )
        if model_confidence < 0.50:
            return TradeVerdict("SKIP", f"model_confidence_too_low={model_confidence:.3f}")
        return TradeVerdict("PLAY", "memory_and_model_aligned")


class SQLiteMemoryStore:
    """SQLite persistence for similar-state empirical memory."""

    def __init__(self, sqlite_path: str):
        self._path = Path(sqlite_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._create_schema()

    def _create_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS memory_predictions (
                id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                symbol TEXT NOT NULL,
                token TEXT NOT NULL,
                feature_vector_json TEXT NOT NULL,
                predicted_direction TEXT NOT NULL,
                model_confidence REAL NOT NULL,
                volume_regime TEXT NOT NULL,
                spread_regime TEXT,
                depth_regime TEXT,
                market_regime TEXT,
                reference_price REAL NOT NULL,
                settlement_horizon_minutes INTEGER NOT NULL,
                settled_at TEXT,
                realized_direction TEXT,
                is_win INTEGER,
                realized_return REAL,
                eval_price REAL,
                inserted_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_mem_symbol_time
                ON memory_predictions(symbol, timestamp);
            CREATE INDEX IF NOT EXISTS idx_mem_symbol_settled
                ON memory_predictions(symbol, settled_at);
            CREATE INDEX IF NOT EXISTS idx_mem_symbol_token
                ON memory_predictions(symbol, token);
            CREATE INDEX IF NOT EXISTS idx_mem_symbol_volume
                ON memory_predictions(symbol, volume_regime);
            """
        )
        self._conn.commit()

    def insert_prediction(
        self,
        *,
        timestamp: str,
        symbol: str,
        token: str,
        feature_vector: list[float],
        predicted_direction: str,
        model_confidence: float,
        volume_regime: str,
        spread_regime: str,
        depth_regime: str,
        market_regime: str,
        reference_price: float,
        settlement_horizon_minutes: int,
    ) -> str:
        prediction_id = str(uuid.uuid4())
        self._conn.execute(
            """
            INSERT INTO memory_predictions(
                id, timestamp, symbol, token, feature_vector_json,
                predicted_direction, model_confidence,
                volume_regime, spread_regime, depth_regime, market_regime,
                reference_price, settlement_horizon_minutes,
                inserted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                prediction_id,
                timestamp,
                symbol.lower(),
                token,
                json.dumps([_safe_float(v) for v in feature_vector]),
                predicted_direction,
                _safe_float(model_confidence),
                volume_regime,
                spread_regime,
                depth_regime,
                market_regime,
                _safe_float(reference_price),
                max(1, int(settlement_horizon_minutes)),
                _utc_iso_now(),
            ),
        )
        self._conn.commit()
        return prediction_id

    def settle_prediction(
        self,
        *,
        prediction_id: str,
        settled_at: str,
        realized_direction: str,
        is_win: bool,
        realized_return: float,
        eval_price: float,
    ) -> None:
        self._conn.execute(
            """
            UPDATE memory_predictions
            SET settled_at = ?,
                realized_direction = ?,
                is_win = ?,
                realized_return = ?,
                eval_price = ?
            WHERE id = ?
            """,
            (
                settled_at,
                realized_direction,
                1 if is_win else 0,
                _safe_float(realized_return),
                _safe_float(eval_price),
                prediction_id,
            ),
        )
        self._conn.commit()

    def settle_latest_unsettled_by_key(
        self,
        *,
        symbol: str,
        pred_minute: str,
        predicted_direction: str,
        settled_at: str,
        realized_direction: str,
        is_win: bool,
        realized_return: float,
        eval_price: float,
    ) -> str | None:
        row = self._conn.execute(
            """
            SELECT id
            FROM memory_predictions
            WHERE symbol = ?
              AND timestamp = ?
              AND predicted_direction = ?
              AND settled_at IS NULL
            ORDER BY inserted_at DESC
            LIMIT 1
            """,
            (symbol.lower(), pred_minute, predicted_direction),
        ).fetchone()
        if row is None:
            return None
        prediction_id = str(row["id"])
        self.settle_prediction(
            prediction_id=prediction_id,
            settled_at=settled_at,
            realized_direction=realized_direction,
            is_win=is_win,
            realized_return=realized_return,
            eval_price=eval_price,
        )
        return prediction_id

    def fetch_settled_candidates(
        self,
        *,
        symbol: str,
        predicted_direction: str,
        volume_regime: str,
        max_age_days: int,
        limit: int,
    ) -> list[sqlite3.Row]:
        max_age = max(1, int(max_age_days))
        since = (datetime.now(timezone.utc) - timedelta(days=max_age)).isoformat()
        return list(
            self._conn.execute(
                """
                SELECT *
                FROM memory_predictions
                WHERE symbol = ?
                  AND settled_at IS NOT NULL
                  AND predicted_direction = ?
                  AND volume_regime = ?
                  AND timestamp >= ?
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (symbol.lower(), predicted_direction, volume_regime, since, max(1, int(limit))),
            )
        )

    def fetch_token_exact_stats(
        self,
        *,
        symbol: str,
        token: str,
        predicted_direction: str,
        volume_regime: str,
    ) -> tuple[int, int]:
        row = self._conn.execute(
            """
            SELECT
              COALESCE(SUM(is_win), 0) AS wins,
              COUNT(*) AS total
            FROM memory_predictions
            WHERE symbol = ?
              AND token = ?
              AND predicted_direction = ?
              AND volume_regime = ?
              AND settled_at IS NOT NULL
            """,
            (symbol.lower(), token, predicted_direction, volume_regime),
        ).fetchone()
        if row is None:
            return 0, 0
        return int(row["wins"]), int(row["total"])


class SimilarStateMemory:
    """High-level similar-state memory service with smoothing and gating inputs."""

    def __init__(
        self,
        sqlite_path: str,
        *,
        k_neighbors: int = 84,
        candidate_limit: int = 2000,
        max_age_days: int = 60,
        bayes_alpha: float = 10.0,
        bayes_beta: float = 10.0,
    ):
        self._store = SQLiteMemoryStore(sqlite_path=sqlite_path)
        self._k_neighbors = max(1, int(k_neighbors))
        self._candidate_limit = max(self._k_neighbors, int(candidate_limit))
        self._max_age_days = max(1, int(max_age_days))
        self._bayes_alpha = max(0.0, float(bayes_alpha))
        self._bayes_beta = max(0.0, float(bayes_beta))

    @property
    def bayes_alpha(self) -> float:
        return self._bayes_alpha

    @property
    def bayes_beta(self) -> float:
        return self._bayes_beta

    def insert_prediction(
        self,
        *,
        timestamp: datetime | str,
        symbol: str,
        token: str,
        feature_vector: list[float],
        predicted_direction: str,
        model_confidence: float,
        regimes: dict[str, str],
        reference_price: float,
        settlement_horizon_minutes: int,
    ) -> str:
        return self._store.insert_prediction(
            timestamp=_to_iso(timestamp),
            symbol=symbol,
            token=token,
            feature_vector=feature_vector,
            predicted_direction=predicted_direction,
            model_confidence=model_confidence,
            volume_regime=regimes.get("volume", "MID"),
            spread_regime=regimes.get("spread", "NORM"),
            depth_regime=regimes.get("depth", "MID"),
            market_regime=regimes.get("market", "UNKNOWN"),
            reference_price=reference_price,
            settlement_horizon_minutes=settlement_horizon_minutes,
        )

    def settle_prediction(
        self,
        *,
        prediction_id: str,
        settled_at: datetime | str,
        realized_direction: str,
        eval_price: float,
    ) -> None:
        # realized_return is notional return over reference price movement
        # relative to stored prediction direction and reference price.
        row = self._store._conn.execute(  # noqa: SLF001 (kept private to avoid overengineering)
            "SELECT reference_price, predicted_direction FROM memory_predictions WHERE id = ?",
            (prediction_id,),
        ).fetchone()
        if row is None:
            return
        reference_price = float(row["reference_price"])
        predicted_direction = str(row["predicted_direction"])
        is_win = predicted_direction == realized_direction
        if reference_price <= 1e-12:
            realized_return = 0.0
        else:
            signed = (eval_price - reference_price) / reference_price
            realized_return = signed if predicted_direction == "LONG" else -signed
        self._store.settle_prediction(
            prediction_id=prediction_id,
            settled_at=_to_iso(settled_at),
            realized_direction=realized_direction,
            is_win=is_win,
            realized_return=realized_return,
            eval_price=eval_price,
        )

    def settle_by_prediction_key(
        self,
        *,
        symbol: str,
        pred_minute: str,
        predicted_direction: str,
        settled_at: datetime | str,
        realized_direction: str,
        reference_price: float,
        eval_price: float,
    ) -> str | None:
        is_win = predicted_direction == realized_direction
        if reference_price <= 1e-12:
            realized_return = 0.0
        else:
            signed = (eval_price - reference_price) / reference_price
            realized_return = signed if predicted_direction == "LONG" else -signed
        return self._store.settle_latest_unsettled_by_key(
            symbol=symbol,
            pred_minute=pred_minute,
            predicted_direction=predicted_direction,
            settled_at=_to_iso(settled_at),
            realized_direction=realized_direction,
            is_win=is_win,
            realized_return=realized_return,
            eval_price=eval_price,
        )

    def _smoothed_winrate(self, wins: int, total: int) -> float:
        return (wins + self._bayes_alpha) / (
            total + self._bayes_alpha + self._bayes_beta
        )

    def lookup_similar(
        self,
        *,
        symbol: str,
        token: str,
        feature_vector: list[float],
        predicted_direction: str,
        regimes: dict[str, str],
    ) -> MemoryLookupResult:
        volume_regime = regimes.get("volume", "MID")

        # Per-token empirical performance is the primary signal.
        # Use exact-token stats first (within the same symbol/direction/volume regime),
        # and only then fall back to broader vector/token-neighbor averaging.
        wins, total = self._store.fetch_token_exact_stats(
            symbol=symbol,
            token=token,
            predicted_direction=predicted_direction,
            volume_regime=volume_regime,
        )
        if total > 0:
            memory_winrate = wins / total
            return MemoryLookupResult(
                memory_winrate=memory_winrate,
                smoothed_memory_winrate=self._smoothed_winrate(wins, total),
                memory_samples=total,
                regime_filtered_samples=total,
                last_5_winrate=memory_winrate,
                last_5_samples=min(5, total),
                match_method="token_exact",
            )

        candidates = self._store.fetch_settled_candidates(
            symbol=symbol,
            predicted_direction=predicted_direction,
            volume_regime=volume_regime,
            max_age_days=self._max_age_days,
            limit=self._candidate_limit,
        )
        regime_samples = len(candidates)
        last_5_rows = candidates[:5]
        last_5_wins = sum(int(r["is_win"] or 0) for r in last_5_rows)
        last_5_total = len(last_5_rows)
        last_5_winrate = (last_5_wins / last_5_total) if last_5_total > 0 else 0.0

        if candidates:
            scored: list[tuple[float, sqlite3.Row]] = []
            for row in candidates:
                vec = json.loads(str(row["feature_vector_json"]))
                dist = _euclidean_distance(feature_vector, [float(v) for v in vec])
                scored.append((dist, row))
            scored.sort(key=lambda x: x[0])
            neighbors = [row for _, row in scored[: self._k_neighbors]]
            wins = sum(int(r["is_win"] or 0) for r in neighbors)
            total = len(neighbors)
            memory_winrate = (wins / total) if total > 0 else 0.0
            return MemoryLookupResult(
                memory_winrate=memory_winrate,
                smoothed_memory_winrate=self._smoothed_winrate(wins, total),
                memory_samples=total,
                regime_filtered_samples=regime_samples,
                last_5_winrate=last_5_winrate,
                last_5_samples=last_5_total,
                match_method="knn_vector",
            )

        # Partial token fallback (direction + symbol across recent settled records)
        broad = self._store._conn.execute(  # noqa: SLF001
            """
            SELECT token, is_win
            FROM memory_predictions
            WHERE symbol = ?
              AND predicted_direction = ?
              AND settled_at IS NOT NULL
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (symbol.lower(), predicted_direction, max(200, self._k_neighbors * 3)),
        ).fetchall()
        if broad:
            scored_tokens = sorted(
                (
                    (_token_jaccard(token, str(row["token"])), row)
                    for row in broad
                ),
                key=lambda x: x[0],
                reverse=True,
            )
            matched = [row for score, row in scored_tokens[: self._k_neighbors] if score > 0.0]
            wins = sum(int(r["is_win"] or 0) for r in matched)
            total = len(matched)
            if total > 0:
                memory_winrate = wins / total
                return MemoryLookupResult(
                    memory_winrate=memory_winrate,
                    smoothed_memory_winrate=self._smoothed_winrate(wins, total),
                    memory_samples=total,
                    regime_filtered_samples=0,
                    last_5_winrate=last_5_winrate,
                    last_5_samples=last_5_total,
                    match_method="token_partial",
                )

        return MemoryLookupResult(
            memory_winrate=0.0,
            smoothed_memory_winrate=self._smoothed_winrate(0, 0),
            memory_samples=0,
            regime_filtered_samples=0,
            last_5_winrate=0.0,
            last_5_samples=0,
            match_method="none",
        )
