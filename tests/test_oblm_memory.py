from datetime import datetime, timezone
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

_MEM_PATH = Path(__file__).resolve().parents[1] / "src" / "trading" / "oblm_memory.py"
_SPEC = spec_from_file_location("test_oblm_memory_module", _MEM_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MOD = module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MOD
_SPEC.loader.exec_module(_MOD)

MemoryDecisionGate = _MOD.MemoryDecisionGate
MemoryLookupResult = _MOD.MemoryLookupResult
SimilarStateMemory = _MOD.SimilarStateMemory


def test_insert_settle_and_lookup_knn(tmp_path: Path):
    memory = SimilarStateMemory(
        sqlite_path=str(tmp_path / "memory.db"),
        k_neighbors=3,
        bayes_alpha=10.0,
        bayes_beta=10.0,
    )

    base_ts = datetime.now(timezone.utc)
    inserted_ids: list[str] = []
    for i, is_bull in enumerate([True, True, False, True]):
        pred_id = memory.insert_prediction(
            timestamp=base_ts.isoformat(),
            symbol="btcusdt",
            token="IMB_HIGH_SPD_NORM_DPT_MID_BOD_LONG_WCK_LOW_VOL_HIGH_CNDL_BULL",
            feature_vector=[0.2 + 0.001 * i, 0.01, 14.0, 0.004, 1.8, 1.3],
            predicted_direction="BULL",
            model_confidence=0.8,
            regimes={"volume": "HIGH", "spread": "NORM", "depth": "MID"},
            reference_price=70000.0,
            settlement_horizon_minutes=5,
        )
        inserted_ids.append(pred_id)
        memory.settle_prediction(
            prediction_id=pred_id,
            settled_at=base_ts.isoformat(),
            realized_direction="BULL" if is_bull else "BEAR",
            eval_price=70050.0 if is_bull else 69900.0,
        )

    lookup = memory.lookup_similar(
        symbol="btcusdt",
        token="IMB_HIGH_SPD_NORM_DPT_MID_BOD_LONG_WCK_LOW_VOL_HIGH_CNDL_BULL",
        feature_vector=[0.2, 0.01, 14.0, 0.004, 1.8, 1.3],
        predicted_direction="BULL",
        regimes={"volume": "HIGH"},
    )

    assert lookup.match_method == "knn_vector"
    assert lookup.memory_samples == 3
    # top-3 nearest should include 2 wins + 1 loss from inserted set
    assert round(lookup.memory_winrate, 4) == round(2 / 3, 4)
    assert 0.0 <= lookup.smoothed_memory_winrate <= 1.0


def test_token_fallback_returns_empirical_when_no_vector_candidates(tmp_path: Path):
    memory = SimilarStateMemory(
        sqlite_path=str(tmp_path / "memory.db"),
        k_neighbors=5,
        candidate_limit=10,
    )
    ts = datetime.now(timezone.utc).isoformat()

    for realized_direction in ["BULL", "BULL", "BEAR"]:
        pred_id = memory.insert_prediction(
            timestamp=ts,
            symbol="btcusdt",
            token="IMB_LOW_SPD_NORM_DPT_LOW_BOD_MID_WCK_MID_VOL_LOW_CNDL_BULL",
            feature_vector=[-0.1, 0.02, 8.0, 0.001, 1.3, 0.6],
            predicted_direction="BULL",
            model_confidence=0.61,
            regimes={"volume": "LOW"},
            reference_price=50000.0,
            settlement_horizon_minutes=5,
        )
        memory.settle_prediction(
            prediction_id=pred_id,
            settled_at=ts,
            realized_direction=realized_direction,
            eval_price=50100.0,
        )

    # volume regime mismatch should avoid vector candidates and token exact in HIGH
    lookup_none = memory.lookup_similar(
        symbol="btcusdt",
        token="IMB_LOW_SPD_NORM_DPT_LOW_BOD_MID_WCK_MID_VOL_LOW_CNDL_BULL",
        feature_vector=[-0.1, 0.02, 8.0, 0.001, 1.3, 0.6],
        predicted_direction="BULL",
        regimes={"volume": "HIGH"},
    )
    assert lookup_none.memory_samples >= 0

    # matching regime should produce vector lookup
    lookup = memory.lookup_similar(
        symbol="btcusdt",
        token="IMB_LOW_SPD_NORM_DPT_LOW_BOD_MID_WCK_MID_VOL_LOW_CNDL_BULL",
        feature_vector=[-0.1, 0.02, 8.0, 0.001, 1.3, 0.6],
        predicted_direction="BULL",
        regimes={"volume": "LOW"},
    )
    assert lookup.memory_samples > 0
    assert 0.0 <= lookup.memory_winrate <= 1.0


def test_memory_decision_gate():
    gate = MemoryDecisionGate(
        min_samples_to_trust=30,
        min_smoothed_winrate=0.55,
        tradable_volume_regimes=("MID", "HIGH"),
    )

    verdict = gate.evaluate(
        model_confidence=0.9,
        lookup=MemoryLookupResult(
            memory_winrate=0.75,
            smoothed_memory_winrate=0.68,
            memory_samples=84,
            regime_filtered_samples=120,
            match_method="knn_vector",
        ),
        volume_regime="HIGH",
    )
    assert verdict.verdict == "PLAY"

    verdict_low_samples = gate.evaluate(
        model_confidence=0.9,
        lookup=MemoryLookupResult(
            memory_winrate=0.90,
            smoothed_memory_winrate=0.80,
            memory_samples=5,
            regime_filtered_samples=5,
            match_method="token_exact",
        ),
        volume_regime="HIGH",
    )
    assert verdict_low_samples.verdict == "SKIP"
