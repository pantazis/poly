from datetime import datetime, timezone
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

_OBLM_PATH = Path(__file__).resolve().parents[1] / "src" / "trading" / "oblm.py"
_SPEC = spec_from_file_location("test_oblm_module", _OBLM_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_OBLM = module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _OBLM
_SPEC.loader.exec_module(_OBLM)

AdaptiveQuantizer = _OBLM.AdaptiveQuantizer
Candle1m = _OBLM.Candle1m
ConfidenceWinrateTracker = _OBLM.ConfidenceWinrateTracker
L2Snapshot = _OBLM.L2Snapshot
MarketState = _OBLM.MarketState


def _market_state(open_price: float, close_price: float) -> MarketState:
    ts = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    return MarketState(
        timestamp=ts,
        l2=L2Snapshot(
            timestamp=ts,
            bids=[(close_price - 0.5, 10.0)],
            asks=[(close_price + 0.5, 10.0)],
        ),
        candle=Candle1m(
            timestamp=ts,
            open=open_price,
            high=max(open_price, close_price) + 1.0,
            low=min(open_price, close_price) - 1.0,
            close=close_price,
            volume=100.0,
        ),
    )


def test_quantizer_adds_bull_candle_direction_token():
    q = AdaptiveQuantizer(rolling_window=20)
    token = q.to_token(_market_state(open_price=100.0, close_price=101.0))
    assert "CNDL_BULL" in token


def test_quantizer_adds_bear_candle_direction_token():
    q = AdaptiveQuantizer(rolling_window=20)
    token = q.to_token(_market_state(open_price=101.0, close_price=100.0))
    assert "CNDL_BEAR" in token


def test_quantizer_adds_doji_candle_direction_token():
    q = AdaptiveQuantizer(rolling_window=20)
    token = q.to_token(_market_state(open_price=100.0, close_price=100.0))
    assert "CNDL_DOJI" in token


def test_confidence_winrate_tracker_uses_cumulative_thresholds():
    tracker = ConfidenceWinrateTracker()

    # 95% correct -> counts for 90..10
    tracker.update(confidence=0.95, correct=True)
    # 85% wrong -> counts for 80..10
    tracker.update(confidence=0.85, correct=False)
    # 15% correct -> counts only for 10
    tracker.update(confidence=0.15, correct=True)

    rows = {int(r["threshold"]): r for r in tracker.summary_rows()}

    # >=90 : 1/1
    assert int(rows[90]["total"]) == 1
    assert int(rows[90]["wins"]) == 1
    assert float(rows[90]["winrate_pct"]) == 100.0

    # >=80 : 1/2
    assert int(rows[80]["total"]) == 2
    assert int(rows[80]["wins"]) == 1
    assert float(rows[80]["winrate_pct"]) == 50.0

    # >=10 : 2/3
    assert int(rows[10]["total"]) == 3
    assert int(rows[10]["wins"]) == 2
    assert round(float(rows[10]["winrate_pct"]), 2) == 66.67
