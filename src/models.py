"""Core data models for the Liquidation Data Collector."""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class LiquidationEvent:
    """A normalized liquidation event from an exchange."""
    
    exchange: str           # Source exchange ("binance")
    symbol: str             # Trading pair (e.g., "BTCUSDT")
    side: str               # "long_liquidated" or "short_liquidated"
    usd_size: float         # Dollar value of liquidation (quantity × price)
    price: float            # Liquidation price
    time: datetime          # Event timestamp (UTC)
    is_significant: bool = False  # True if usd_size >= threshold


@dataclass
class WindowAggregation:
    """Aggregated liquidation data for a time window."""
    
    window_minutes: int         # 1, 5, 10, or 15
    long_liquidated_usd: float  # Total USD from long liquidations
    short_liquidated_usd: float # Total USD from short liquidations
    event_count: int            # Number of significant events


@dataclass
class HealthMetrics:
    """System health metrics."""
    
    events_received_total: int
    events_filtered_significant: int
    connection_uptime_seconds: float
    last_event_time: datetime | None
    is_connected: bool


@dataclass
class CollectorConfig:
    """Configuration for the LiquidationCollector."""
    
    data_dir: Path = field(default_factory=lambda: Path("./data"))
    significance_threshold_usd: float = 25_000.0
    flush_interval_seconds: float = 5.0
