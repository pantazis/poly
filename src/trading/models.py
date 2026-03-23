"""Core data models for the Liquidation Trading Bot.

This module defines the dataclasses used throughout the trading bot:
- EntrySignal: Liquidation-based entry signal data
- PolymarketOrder: Polymarket order details
- BinancePosition: Binance Futures hedge position details
- TradePair: Combined Polymarket bet and Binance hedge
- TradeLogEntry: Trade event logging structure
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class EntrySignal:
    """A liquidation-based entry signal for trade execution.
    
    Generated when liquidation aggregations meet threshold criteria.
    
    Attributes:
        signal_type: "long_liquidation" or "short_liquidation" (dominant side)
        liquidation_usd: Total USD liquidated in the window (long_usd + short_usd)
        timestamp: Signal generation time (UTC)
        dominant_side: "long_liquidated" or "short_liquidated"
        long_usd: Long liquidation USD amount in window
        short_usd: Short liquidation USD amount in window
    """
    
    signal_type: str        # "long_liquidation" or "short_liquidation"
    liquidation_usd: float  # Total USD liquidated in window
    timestamp: datetime     # Signal generation time (UTC)
    dominant_side: str      # "long_liquidated" or "short_liquidated"
    long_usd: float         # Long liquidation amount
    short_usd: float        # Short liquidation amount


@dataclass
class PolymarketOrder:
    """A Polymarket CLOB order for binary options.
    
    Represents an order placed on Polymarket's 5-minute BTC binary options.
    
    Attributes:
        order_id: Unique order identifier from Polymarket
        market_id: 5-minute BTC binary market identifier
        outcome: "UP" or "DOWN"
        side: Order side (always "BUY" for this strategy)
        size: USDC amount wagered
        price: Limit price (0-1 range)
        status: "pending", "filled", "cancelled", or "expired"
        fill_price: Actual fill price (None if not filled)
        fill_time: Time of fill (None if not filled)
    """
    
    order_id: str
    market_id: str          # 5-minute BTC binary market
    outcome: str            # "UP" or "DOWN"
    side: str               # Always "BUY"
    size: float             # USDC amount
    price: float            # Limit price (0-1)
    status: str             # "pending", "filled", "cancelled", "expired"
    fill_price: float | None
    fill_time: datetime | None
    shares_bought: float | None = None
    max_profit: float | None = None
    max_loss: float | None = None


@dataclass
class BinancePosition:
    """A Binance Futures hedge position.
    
    Represents a leveraged position on Binance Futures used to hedge
    the Polymarket binary option bet.
    
    Attributes:
        position_id: Unique position identifier
        symbol: Trading pair (e.g., "BTCUSDT")
        side: "LONG" or "SHORT"
        size: Position size in BTC
        leverage: Leverage multiplier (e.g., 3)
        entry_price: Position entry price
        margin_mode: Margin mode ("isolated")
        status: "open" or "closed"
        pnl: Realized PnL when closed (None if open)
    """
    
    position_id: str
    symbol: str             # "BTCUSDT"
    side: str               # "LONG" or "SHORT"
    size: float             # Position size in BTC
    leverage: int           # Leverage multiplier
    entry_price: float
    margin_mode: str        # "isolated"
    status: str             # "open", "closed"
    pnl: float | None       # Realized PnL when closed


@dataclass
class TradePair:
    """A combined Polymarket bet and Binance hedge trade.
    
    Tracks the full lifecycle of a trade pair from entry to expiry.
    
    Attributes:
        trade_id: Unique UUID identifier
        polymarket_order: The Polymarket binary option order
        binance_position: The Binance hedge position (None if hedge failed)
        direction: "UP" or "DOWN" (matches Polymarket outcome)
        entry_time: When the Polymarket order was filled
        expiry_time: entry_time + 5 minutes (when hedge closes)
        status: "pending", "open", "closing", or "closed"
        polymarket_pnl: PnL from Polymarket bet (None until settled)
        binance_pnl: PnL from Binance hedge (None until closed)
        total_pnl: Combined PnL (None until both settled)
    """
    
    trade_id: str
    polymarket_order: PolymarketOrder
    binance_position: BinancePosition | None
    direction: str          # "UP" or "DOWN"
    entry_time: datetime
    expiry_time: datetime   # entry_time + 5 minutes
    status: str             # "pending", "open", "closing", "closed"
    polymarket_pnl: float | None
    binance_pnl: float | None
    total_pnl: float | None
    reference_entry_price: float | None = None
    reference_exit_price: float | None = None


@dataclass
class TradeLogEntry:
    """A trade event log entry for CSV logging.
    
    Records all trade-related events for analysis and debugging.
    
    Attributes:
        timestamp: Event timestamp (UTC)
        event_type: "signal", "order_placed", "order_filled", "position_closed"
        trade_id: UUID of associated TradePair (None for signals)
        exchange: "polymarket" or "binance" (None for signals)
        side: "UP", "DOWN", "LONG", or "SHORT" (None for some events)
        size: Order/position size in USD (None for some events)
        price: Order/fill price (None for some events)
        pnl: Realized PnL (None except for position_closed)
        is_dry_run: True if this was a simulated trade
        details: JSON string with additional event data (None if no extra data)
    """
    
    timestamp: datetime
    event_type: str         # "signal", "order_placed", "order_filled", "position_closed"
    trade_id: str | None
    exchange: str | None    # "polymarket" or "binance"
    side: str | None        # "UP", "DOWN", "LONG", "SHORT"
    size: float | None
    price: float | None
    pnl: float | None
    is_dry_run: bool
    details: str | None     # JSON string with additional data
