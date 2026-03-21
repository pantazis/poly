"""SignalDetector - Monitors liquidation aggregations and generates entry signals."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from ..collector import LiquidationCollector
from .models import EntrySignal

logger = logging.getLogger(__name__)


class SignalDetector:
    """Monitors liquidation aggregations and generates entry signals.
    
    The SignalDetector polls the LiquidationCollector's aggregations at 1-second
    intervals and generates EntrySignal events when liquidation thresholds are met.
    
    Signal generation rules:
    - Total liquidation (long + short) must be >= threshold_min AND <= threshold_max
    - Long and short liquidation amounts must not be equal
    - No position can be currently open
    """
    
    def __init__(
        self,
        collector: LiquidationCollector,
        threshold_min: float = 25_000.0,
        threshold_max: float = 100_000.0,
        window_minutes: int = 5,
        on_signal: Callable[[EntrySignal], Awaitable[None]] | None = None,
    ):
        """Initialize the SignalDetector.
        
        Args:
            collector: LiquidationCollector instance to get aggregations from
            threshold_min: Minimum liquidation USD to trigger signal
            threshold_max: Maximum liquidation USD for valid signal
            window_minutes: Aggregation window to monitor (1, 5, 10, or 15)
            on_signal: Async callback invoked when signal is generated
        """
        self._collector = collector
        self._threshold_min = threshold_min
        self._threshold_max = threshold_max
        self._window_minutes = window_minutes
        self._on_signal = on_signal
        
        self._running = False
        self._position_open = False
        self._poll_task: asyncio.Task | None = None
    
    async def start(self) -> None:
        """Start monitoring aggregations. Polls at 1-second intervals."""
        if self._running:
            logger.warning("SignalDetector already running")
            return
        
        self._running = True
        logger.info(
            f"SignalDetector started: window={self._window_minutes}min, "
            f"threshold=${self._threshold_min:,.0f}-${self._threshold_max:,.0f}"
        )
        self._poll_task = asyncio.create_task(self._poll_loop())
    
    async def stop(self) -> None:
        """Stop monitoring."""
        if not self._running:
            return
        
        self._running = False
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
            self._poll_task = None
        
        logger.info("SignalDetector stopped")
    
    def set_position_open(self, is_open: bool) -> None:
        """Set whether a position is currently open (blocks new signals).
        
        Args:
            is_open: True if a position is open, False otherwise
        """
        self._position_open = is_open
        if is_open:
            logger.debug("Position opened - signal generation blocked")
        else:
            logger.debug("Position closed - signal generation enabled")
    
    def check_signal(self) -> EntrySignal | None:
        """Check current aggregations for entry signal.
        
        Returns:
            EntrySignal if conditions are met, None otherwise.
            Returns None if:
            - Position is currently open
            - No aggregation found for the configured window
            - Total liquidation is outside threshold range
            - Long and short liquidation amounts are equal
        """
        # Block signals when position is open
        if self._position_open:
            return None
        
        # Get aggregations from collector
        aggregations = self._collector.get_aggregations()
        
        # Find the aggregation for our configured window
        target_agg = None
        for agg in aggregations:
            if agg.window_minutes == self._window_minutes:
                target_agg = agg
                break
        
        if target_agg is None:
            logger.warning(f"No aggregation found for {self._window_minutes}-minute window")
            return None
        
        long_usd = target_agg.long_liquidated_usd
        short_usd = target_agg.short_liquidated_usd
        total = long_usd + short_usd
        
        # Check threshold conditions
        if total < self._threshold_min or total > self._threshold_max:
            return None
        
        # Check that long and short are not equal
        if long_usd == short_usd:
            return None
        
        # Determine signal type and dominant side
        if long_usd > short_usd:
            signal_type = "long_liquidation"
            dominant_side = "long_liquidated"
        else:
            signal_type = "short_liquidation"
            dominant_side = "short_liquidated"
        
        # Create and return the signal
        signal = EntrySignal(
            signal_type=signal_type,
            liquidation_usd=total,
            timestamp=datetime.now(timezone.utc),
            dominant_side=dominant_side,
            long_usd=long_usd,
            short_usd=short_usd,
        )
        
        logger.info(
            f"Entry signal generated: {signal_type}, "
            f"total=${total:,.0f} (long=${long_usd:,.0f}, short=${short_usd:,.0f})"
        )
        
        return signal
    
    async def _poll_loop(self) -> None:
        """Internal polling loop that checks for signals every second."""
        while self._running:
            try:
                signal = self.check_signal()
                if signal and self._on_signal:
                    await self._on_signal(signal)
            except Exception as e:
                logger.error(f"Error in signal detection: {e}")
            
            await asyncio.sleep(1.0)
