"""Tests for EventFilter."""

from datetime import datetime, timezone

from src.models import LiquidationEvent
from src.filter import EventFilter


def _make_event(usd_size: float) -> LiquidationEvent:
    """Helper to create a test event."""
    return LiquidationEvent(
        exchange="binance",
        symbol="BTCUSDT",
        side="long_liquidated",
        usd_size=usd_size,
        price=50000.0,
        time=datetime.now(timezone.utc),
        is_significant=False,
    )


def test_event_above_threshold_is_significant():
    """Events above threshold should be marked significant."""
    filter = EventFilter(threshold_usd=25_000.0)
    event = _make_event(30_000.0)
    
    result = filter.classify(event)
    
    assert result.is_significant is True


def test_event_below_threshold_is_not_significant():
    """Events below threshold should not be marked significant."""
    filter = EventFilter(threshold_usd=25_000.0)
    event = _make_event(10_000.0)
    
    result = filter.classify(event)
    
    assert result.is_significant is False


def test_event_at_threshold_is_significant():
    """Events exactly at threshold should be marked significant."""
    filter = EventFilter(threshold_usd=25_000.0)
    event = _make_event(25_000.0)
    
    result = filter.classify(event)
    
    assert result.is_significant is True


def test_threshold_property():
    """Threshold property should return configured value."""
    filter = EventFilter(threshold_usd=50_000.0)
    
    assert filter.threshold == 50_000.0
