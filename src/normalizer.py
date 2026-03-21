"""DataNormalizer - Transforms raw exchange data into unified format."""

from datetime import datetime, timezone
from typing import Any

from .models import LiquidationEvent


class DataNormalizer:
    """Transforms raw exchange data into unified LiquidationEvent format."""
    
    @staticmethod
    def normalize_binance(raw: dict[str, Any]) -> LiquidationEvent:
        """
        Transform Binance forceOrder message to LiquidationEvent.
        
        Side mapping:
        - "SELL" → "long_liquidated" (long position closed, price going down)
        - "BUY" → "short_liquidated" (short position closed, price going up)
        
        Args:
            raw: Raw Binance forceOrder WebSocket message
            
        Returns:
            Normalized LiquidationEvent
        """
        order = raw["o"]
        
        # Extract fields
        symbol = order["s"]
        binance_side = order["S"]
        price = float(order["p"])
        avg_price = float(order["ap"])
        filled_qty = float(order["z"])
        trade_time_ms = order["T"]
        
        # Map side
        side = "long_liquidated" if binance_side == "SELL" else "short_liquidated"
        
        # Calculate USD size
        usd_size = filled_qty * avg_price
        
        # Convert timestamp
        time = datetime.fromtimestamp(trade_time_ms / 1000, tz=timezone.utc)
        
        return LiquidationEvent(
            exchange="binance",
            symbol=symbol,
            side=side,
            usd_size=usd_size,
            price=price,
            time=time,
            is_significant=False,
        )
    
    @staticmethod
    def to_dict(event: LiquidationEvent) -> dict[str, Any]:
        """Serialize LiquidationEvent to dictionary."""
        return {
            "exchange": event.exchange,
            "symbol": event.symbol,
            "side": event.side,
            "usd_size": event.usd_size,
            "price": event.price,
            "time": event.time.isoformat(),
            "is_significant": event.is_significant,
        }
    
    @staticmethod
    def from_dict(data: dict[str, Any]) -> LiquidationEvent:
        """Deserialize LiquidationEvent from dictionary."""
        return LiquidationEvent(
            exchange=data["exchange"],
            symbol=data["symbol"],
            side=data["side"],
            usd_size=data["usd_size"],
            price=data["price"],
            time=datetime.fromisoformat(data["time"]),
            is_significant=data["is_significant"],
        )
