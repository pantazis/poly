"""Tests for the SignalDetector component."""

import asyncio
from datetime import datetime, timezone
from unittest.mock import MagicMock, AsyncMock

import pytest

from src.models import WindowAggregation
from src.trading.signal_detector import SignalDetector


class MockCollector:
    """Mock LiquidationCollector for testing."""
    
    def __init__(self, aggregations: list[WindowAggregation] | None = None):
        self._aggregations = aggregations or []
    
    def get_aggregations(self) -> list[WindowAggregation]:
        return self._aggregations
    
    def set_aggregations(self, aggregations: list[WindowAggregation]) -> None:
        self._aggregations = aggregations


class TestSignalDetectorCheckSignal:
    """Tests for SignalDetector.check_signal() method."""
    
    def test_no_signal_when_position_open(self):
        """Should return None when position is open."""
        collector = MockCollector([
            WindowAggregation(
                window_minutes=5,
                long_liquidated_usd=30000.0,
                short_liquidated_usd=10000.0,
                event_count=5,
            )
        ])
        detector = SignalDetector(collector, threshold_min=25000, threshold_max=100000)
        detector.set_position_open(True)
        
        signal = detector.check_signal()
        assert signal is None
    
    def test_no_signal_below_threshold_min(self):
        """Should return None when total is below threshold_min."""
        collector = MockCollector([
            WindowAggregation(
                window_minutes=5,
                long_liquidated_usd=10000.0,
                short_liquidated_usd=5000.0,
                event_count=3,
            )
        ])
        detector = SignalDetector(collector, threshold_min=25000, threshold_max=100000)
        
        signal = detector.check_signal()
        assert signal is None
    
    def test_no_signal_above_threshold_max(self):
        """Should return None when total is above threshold_max."""
        collector = MockCollector([
            WindowAggregation(
                window_minutes=5,
                long_liquidated_usd=80000.0,
                short_liquidated_usd=50000.0,
                event_count=10,
            )
        ])
        detector = SignalDetector(collector, threshold_min=25000, threshold_max=100000)
        
        signal = detector.check_signal()
        assert signal is None
    
    def test_no_signal_when_equal_liquidations(self):
        """Should return None when long and short liquidations are equal."""
        collector = MockCollector([
            WindowAggregation(
                window_minutes=5,
                long_liquidated_usd=25000.0,
                short_liquidated_usd=25000.0,
                event_count=6,
            )
        ])
        detector = SignalDetector(collector, threshold_min=25000, threshold_max=100000)
        
        signal = detector.check_signal()
        assert signal is None
    
    def test_long_liquidation_signal(self):
        """Should generate long_liquidation signal when long > short."""
        collector = MockCollector([
            WindowAggregation(
                window_minutes=5,
                long_liquidated_usd=35000.0,
                short_liquidated_usd=15000.0,
                event_count=5,
            )
        ])
        detector = SignalDetector(collector, threshold_min=25000, threshold_max=100000)
        
        signal = detector.check_signal()
        
        assert signal is not None
        assert signal.signal_type == "long_liquidation"
        assert signal.dominant_side == "long_liquidated"
        assert signal.liquidation_usd == 50000.0
        assert signal.long_usd == 35000.0
        assert signal.short_usd == 15000.0
        assert signal.timestamp.tzinfo == timezone.utc
    
    def test_short_liquidation_signal(self):
        """Should generate short_liquidation signal when short > long."""
        collector = MockCollector([
            WindowAggregation(
                window_minutes=5,
                long_liquidated_usd=10000.0,
                short_liquidated_usd=40000.0,
                event_count=5,
            )
        ])
        detector = SignalDetector(collector, threshold_min=25000, threshold_max=100000)
        
        signal = detector.check_signal()
        
        assert signal is not None
        assert signal.signal_type == "short_liquidation"
        assert signal.dominant_side == "short_liquidated"
        assert signal.liquidation_usd == 50000.0
        assert signal.long_usd == 10000.0
        assert signal.short_usd == 40000.0
    
    def test_signal_at_threshold_min_boundary(self):
        """Should generate signal when total equals threshold_min."""
        collector = MockCollector([
            WindowAggregation(
                window_minutes=5,
                long_liquidated_usd=15000.0,
                short_liquidated_usd=10000.0,
                event_count=3,
            )
        ])
        detector = SignalDetector(collector, threshold_min=25000, threshold_max=100000)
        
        signal = detector.check_signal()
        
        assert signal is not None
        assert signal.liquidation_usd == 25000.0
    
    def test_signal_at_threshold_max_boundary(self):
        """Should generate signal when total equals threshold_max."""
        collector = MockCollector([
            WindowAggregation(
                window_minutes=5,
                long_liquidated_usd=60000.0,
                short_liquidated_usd=40000.0,
                event_count=10,
            )
        ])
        detector = SignalDetector(collector, threshold_min=25000, threshold_max=100000)
        
        signal = detector.check_signal()
        
        assert signal is not None
        assert signal.liquidation_usd == 100000.0
    
    def test_uses_configured_window(self):
        """Should use the configured window_minutes to find aggregation."""
        collector = MockCollector([
            WindowAggregation(
                window_minutes=1,
                long_liquidated_usd=5000.0,
                short_liquidated_usd=2000.0,
                event_count=2,
            ),
            WindowAggregation(
                window_minutes=5,
                long_liquidated_usd=30000.0,
                short_liquidated_usd=10000.0,
                event_count=5,
            ),
            WindowAggregation(
                window_minutes=10,
                long_liquidated_usd=50000.0,
                short_liquidated_usd=20000.0,
                event_count=8,
            ),
        ])
        
        # Using 5-minute window should find signal
        detector_5min = SignalDetector(collector, threshold_min=25000, threshold_max=100000, window_minutes=5)
        signal = detector_5min.check_signal()
        assert signal is not None
        assert signal.liquidation_usd == 40000.0
        
        # Using 1-minute window should not find signal (below threshold)
        detector_1min = SignalDetector(collector, threshold_min=25000, threshold_max=100000, window_minutes=1)
        signal = detector_1min.check_signal()
        assert signal is None
    
    def test_no_signal_when_window_not_found(self):
        """Should return None when configured window is not in aggregations."""
        collector = MockCollector([
            WindowAggregation(
                window_minutes=1,
                long_liquidated_usd=30000.0,
                short_liquidated_usd=10000.0,
                event_count=5,
            ),
        ])
        detector = SignalDetector(collector, threshold_min=25000, threshold_max=100000, window_minutes=5)
        
        signal = detector.check_signal()
        assert signal is None


class TestSignalDetectorPositionState:
    """Tests for SignalDetector position state management."""
    
    def test_set_position_open_blocks_signals(self):
        """Setting position open should block signal generation."""
        collector = MockCollector([
            WindowAggregation(
                window_minutes=5,
                long_liquidated_usd=30000.0,
                short_liquidated_usd=10000.0,
                event_count=5,
            )
        ])
        detector = SignalDetector(collector, threshold_min=25000, threshold_max=100000)
        
        # Signal should be generated when no position
        signal = detector.check_signal()
        assert signal is not None
        
        # Block signals
        detector.set_position_open(True)
        signal = detector.check_signal()
        assert signal is None
        
        # Unblock signals
        detector.set_position_open(False)
        signal = detector.check_signal()
        assert signal is not None


class TestSignalDetectorStartStop:
    """Tests for SignalDetector start/stop lifecycle."""
    
    @pytest.mark.asyncio
    async def test_start_and_stop(self):
        """Should start and stop without errors."""
        collector = MockCollector([])
        detector = SignalDetector(collector)
        
        await detector.start()
        assert detector._running is True
        assert detector._poll_task is not None
        
        await detector.stop()
        assert detector._running is False
        assert detector._poll_task is None
    
    @pytest.mark.asyncio
    async def test_callback_invoked_on_signal(self):
        """Should invoke callback when signal is generated."""
        collector = MockCollector([
            WindowAggregation(
                window_minutes=5,
                long_liquidated_usd=30000.0,
                short_liquidated_usd=10000.0,
                event_count=5,
            )
        ])
        
        received_signals = []
        
        async def on_signal(signal):
            received_signals.append(signal)
        
        detector = SignalDetector(
            collector,
            threshold_min=25000,
            threshold_max=100000,
            on_signal=on_signal,
        )
        
        await detector.start()
        # Wait for at least one poll cycle
        await asyncio.sleep(1.5)
        await detector.stop()
        
        assert len(received_signals) >= 1
        assert received_signals[0].signal_type == "long_liquidation"
    
    @pytest.mark.asyncio
    async def test_double_start_is_safe(self):
        """Starting twice should not create duplicate tasks."""
        collector = MockCollector([])
        detector = SignalDetector(collector)
        
        await detector.start()
        first_task = detector._poll_task
        
        await detector.start()  # Should be a no-op
        assert detector._poll_task is first_task
        
        await detector.stop()
    
    @pytest.mark.asyncio
    async def test_stop_when_not_running_is_safe(self):
        """Stopping when not running should not raise errors."""
        collector = MockCollector([])
        detector = SignalDetector(collector)
        
        # Should not raise
        await detector.stop()
