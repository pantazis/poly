from datetime import datetime, timedelta, timezone
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys


_OBLM_V2_PATH = Path(__file__).resolve().parents[1] / "src" / "trading" / "oblm_v2.py"
_SPEC = spec_from_file_location("test_oblm_v2_module", _OBLM_V2_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_OBLM_V2 = module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _OBLM_V2
_SPEC.loader.exec_module(_OBLM_V2)

AdaptiveQuantizer = _OBLM_V2.AdaptiveQuantizer
L2Snapshot = _OBLM_V2.L2Snapshot
Candle1m = _OBLM_V2.Candle1m
MarketState = _OBLM_V2.MarketState
RollingIndicatorState = _OBLM_V2.RollingIndicatorState
SymbolicPatternTracker = _OBLM_V2.SymbolicPatternTracker
OBLMEngine = _OBLM_V2.OBLMEngine
ConfidenceWinrateTracker = _OBLM_V2.ConfidenceWinrateTracker


def _market_state(ts: datetime, open_price: float, close_price: float, volume: float = 100.0) -> MarketState:
    return MarketState(
        timestamp=ts,
        l2=L2Snapshot(
            timestamp=ts,
            bids=[(close_price - 0.5, 10.0), (close_price - 1.0, 8.0)],
            asks=[(close_price + 0.5, 10.0), (close_price + 1.0, 8.0)],
        ),
        candle=Candle1m(
            timestamp=ts,
            open=open_price,
            high=max(open_price, close_price) + 0.5,
            low=min(open_price, close_price) - 0.5,
            close=close_price,
            volume=volume,
        ),
    )


def test_quantizer_token_includes_vol2h_and_regime_fields():
    ts = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    q = AdaptiveQuantizer(rolling_window=20)
    indicators = RollingIndicatorState(rolling_window=120)

    context = indicators.update(_market_state(ts, 100.0, 101.0, volume=100.0).candle)
    token = q.to_token(_market_state(ts, 100.0, 101.0, volume=100.0), context)

    assert "VOL2H_" in token
    assert "RGM_" in token
    assert "RGF_" in token


def test_pattern_tracker_produces_bullish_gradient_for_win_dominant_fragment():
    tracker = SymbolicPatternTracker(sequence_len=3, ngram_size=2)
    base = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)

    win_tokens = [
        "IMB_VHIGH_SPD_NORM_DPT_MID_BOD_LONG_WCK_MID_VOL_HIGH_VOL2H_HIGH_RGM_HIGH_RGF_HIGH_CNDL_BULL",
        "IMB_VHIGH_SPD_NORM_DPT_MID_BOD_MID_WCK_MID_VOL_HIGH_VOL2H_HIGH_RGM_HIGH_RGF_HIGH_CNDL_BULL",
        "IMB_VHIGH_SPD_NORM_DPT_MID_BOD_SHORT_WCK_MID_VOL_MID_VOL2H_HIGH_RGM_HIGH_RGF_HIGH_CNDL_BULL",
    ]
    for token in win_tokens:
        tracker.record_prediction(base, token)
    settled = tracker.settle_prediction(base, is_win=True)
    assert any(row["signal"] == "Bullish" for row in settled["gradient_rows"])


def test_confidence_winrate_tracker_uses_rolling_30_window():
    tracker = ConfidenceWinrateTracker(thresholds=[50], rolling_window=30)

    # 120 outcomes: first 20 losses, next 100 wins.
    for i in range(120):
        tracker.update(confidence=0.9, correct=(i >= 20), vol2h_bucket="MID")

    row = tracker.summary_rows()[0]
    assert row["threshold"] == 50
    assert row["total"] == 30
    assert row["wins"] == 30

    # Add 10 losses -> rolling window should now contain 20 wins + 10 losses.
    for _ in range(10):
        tracker.update(confidence=0.9, correct=False, vol2h_bucket="MID")

    row2 = tracker.summary_rows()[0]
    assert row2["total"] == 30
    assert row2["wins"] == 20


def test_engine_settles_prediction_after_holding_minutes():
    engine = OBLMEngine(holding_minutes=1, warmup_candles=1)
    t0 = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(minutes=1)

    # First state creates a long pending prediction (default 0.5 => BULL).
    engine.process_market_state(_market_state(t0, open_price=100.0, close_price=100.0, volume=100.0))
    assert engine.pending_count >= 1

    # Drop below trailing stop, causing settlement for the first prediction.
    engine.process_market_state(_market_state(t1, open_price=100.0, close_price=98.0, volume=100.0))
    settlements = engine.last_settlements
    assert len(settlements) >= 1
    assert settlements[0]["predicted"] == "BULL"
    assert settlements[0]["correct"] is False


def test_engine_default_allows_24_7_trading():
    engine = OBLMEngine(warmup_candles=1)

    sunday = datetime(2026, 1, 4, 10, 0, tzinfo=timezone.utc)  # Sunday
    out = engine.process_market_state(_market_state(sunday, open_price=100.0, close_price=101.0))
    assert out.action == "TRADE"


def test_engine_blocks_trading_outside_configured_weekday_session_when_enabled():
    engine = OBLMEngine(
        warmup_candles=1,
        trading_session_enabled=True,
        trading_session_weekdays_only=True,
        trading_session_start_hour_utc=9,
        trading_session_end_hour_utc=19,
    )

    sunday = datetime(2026, 1, 4, 10, 0, tzinfo=timezone.utc)  # Sunday
    out = engine.process_market_state(_market_state(sunday, open_price=100.0, close_price=101.0))
    assert out.action == "NO_TRADE"
    assert out.reason == "outside_trading_session"

    monday = datetime(2026, 1, 5, 10, 0, tzinfo=timezone.utc)  # Monday 10:00 UTC
    inside = engine.process_market_state(_market_state(monday, open_price=101.0, close_price=102.0))
    assert inside.action == "TRADE"
