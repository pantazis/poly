"""HealthMonitor - Tracks system health metrics."""

import logging
from datetime import datetime, timezone

from .connector import BinanceConnector
from .models import HealthMetrics, LiquidationEvent

logger = logging.getLogger(__name__)

STALE_THRESHOLD_SECONDS = 300  # 5 minutes


class HealthMonitor:
    """Monitors system health and logs warnings."""
    
    def __init__(self, connector: BinanceConnector):
        self._connector = connector
        self._events_received_total = 0
        self._events_filtered_significant = 0
        self._last_event_time: datetime | None = None
    
    def record_event(self, event: LiquidationEvent) -> None:
        """Record event receipt for metrics."""
        self._events_received_total += 1
        self._last_event_time = datetime.now(timezone.utc)
        
        if event.is_significant:
            self._events_filtered_significant += 1
    
    def get_metrics(self) -> HealthMetrics:
        """Returns current health metrics."""
        return HealthMetrics(
            events_received_total=self._events_received_total,
            events_filtered_significant=self._events_filtered_significant,
            connection_uptime_seconds=self._connector.uptime_seconds,
            last_event_time=self._last_event_time,
            is_connected=self._connector.is_connected,
        )
    
    async def check_health(self) -> None:
        """
        Periodic health check. Logs warning if no events for 5 minutes.
        Should be called periodically (e.g., every 30 seconds).
        """
        if not self._connector.is_connected:
            logger.warning("Binance WebSocket is not connected")
            return
        
        if self._last_event_time is None:
            return
        
        now = datetime.now(timezone.utc)
        seconds_since_last = (now - self._last_event_time).total_seconds()
        
        if seconds_since_last > STALE_THRESHOLD_SECONDS:
            logger.warning(
                f"No events received for {seconds_since_last:.0f} seconds "
                f"(threshold: {STALE_THRESHOLD_SECONDS}s)"
            )
