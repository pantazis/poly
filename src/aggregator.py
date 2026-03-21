"""TimeAggregator - Maintains rolling time-window aggregations."""

from datetime import datetime, timedelta, timezone

from .models import LiquidationEvent, WindowAggregation


class TimeAggregator:
    """Maintains rolling time-window aggregations of liquidation data."""
    
    WINDOWS = [1, 5, 10, 15]  # minutes
    
    def __init__(self):
        self._events: list[LiquidationEvent] = []
    
    def add_event(self, event: LiquidationEvent) -> None:
        """Add event to aggregation. Only significant events are counted."""
        if event.is_significant:
            self._events.append(event)
    
    def prune_expired(self) -> None:
        """Remove events older than max window (15 minutes)."""
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(minutes=max(self.WINDOWS))
        self._events = [e for e in self._events if e.time >= cutoff]
    
    def get_aggregations(self) -> list[WindowAggregation]:
        """
        Returns current aggregations for all time windows.
        Prunes expired events before calculating.
        """
        self.prune_expired()
        now = datetime.now(timezone.utc)
        
        results = []
        for window_minutes in self.WINDOWS:
            cutoff = now - timedelta(minutes=window_minutes)
            
            long_usd = 0.0
            short_usd = 0.0
            count = 0
            
            for event in self._events:
                if event.time >= cutoff:
                    count += 1
                    if event.side == "long_liquidated":
                        long_usd += event.usd_size
                    else:
                        short_usd += event.usd_size
            
            results.append(WindowAggregation(
                window_minutes=window_minutes,
                long_liquidated_usd=long_usd,
                short_liquidated_usd=short_usd,
                event_count=count,
            ))
        
        return results
