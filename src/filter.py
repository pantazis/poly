"""EventFilter - Classifies liquidation events by significance."""

from dataclasses import replace

from .models import LiquidationEvent


class EventFilter:
    """Filters and classifies liquidation events by USD size."""
    
    def __init__(self, threshold_usd: float = 25_000.0):
        """
        Args:
            threshold_usd: Minimum USD size for significant classification
        """
        self._threshold_usd = threshold_usd
    
    def classify(self, event: LiquidationEvent) -> LiquidationEvent:
        """
        Returns event with is_significant field set based on threshold.
        
        Args:
            event: LiquidationEvent to classify
            
        Returns:
            New LiquidationEvent with is_significant set
        """
        is_significant = event.usd_size >= self._threshold_usd
        return replace(event, is_significant=is_significant)
    
    @property
    def threshold(self) -> float:
        """Returns current significance threshold."""
        return self._threshold_usd
