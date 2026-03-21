"""Tests for TimeAggregator."""

from datetime import datetime, timedelta, timezone

from src.models import LiquidationEvent
from src.aggregator import TimeAggregator


def _make_event(
    side: str = "long_liquidated",
    usd_size: float = 50000.0,
    minutes_ago: float = 0,
) -> LiquidationEvent:
    """Helper to create a test event."""
    time = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return LiquidationEvent(
        exchange="binance",
        symbol="BTCUSDT",
        side=side,
        usd_size=usd_size,
        price=50000.0,
        time=time,
        is_significant=True,
    )


def test_empty_aggregation():
    """Empty aggregator should return zeros."""
    agg = TimeAggregator()
    
    results = agg.get_aggregations()
    
    assert len(results) == 4
    for r in results:
        assert r.long_liquidated_usd == 0.0
        assert r.short_liquidated_usd == 0.0
        assert r.event_count == 0


def test_single_event_aggregation():
    """Single event should be counted in all windows."""
    agg = TimeAggregator()
    event = _make_event(side="long_liquidated", usd_size=30000.0, minutes_ago=0)
    
    agg.add_event(event)
    results = agg.get_aggregations()
    
    for r in results:
        assert r.long_liquidated_usd == 30000.0
        assert r.short_liquidated_usd == 0.0
        assert r.event_count == 1


def test_expired_event_excluded():
    """Events older than window should be excluded."""
    agg = TimeAggregator()
    
    # Event 2 minutes ago - should be in 5m, 10m, 15m but not 1m
    event = _make_event(minutes_ago=2)
    agg.add_event(event)
    
    results = agg.get_aggregations()
    results_by_window = {r.window_minutes: r for r in results}
    
    assert results_by_window[1].event_count == 0
    assert results_by_window[5].event_count == 1
    assert results_by_window[10].event_count == 1
    assert results_by_window[15].event_count == 1


def test_non_significant_events_ignored():
    """Non-significant events should not be added."""
    agg = TimeAggregator()
    event = LiquidationEvent(
        exchange="binance",
        symbol="BTCUSDT",
        side="long_liquidated",
        usd_size=1000.0,
        price=50000.0,
        time=datetime.now(timezone.utc),
        is_significant=False,  # Not significant
    )
    
    agg.add_event(event)
    results = agg.get_aggregations()
    
    for r in results:
        assert r.event_count == 0
