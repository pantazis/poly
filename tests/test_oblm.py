from datetime import datetime, timezone

from src.trading.oblm import AdaptiveQuantizer, Candle1m, L2Snapshot, MarketState


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
