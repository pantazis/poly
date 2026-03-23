"""Position management for the Liquidation Trading Bot.

This module provides the PositionManager class for tracking open positions
and managing their lifecycle, including expiry handling and PnL calculation.
"""

import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone

from .binance_trader import BinanceTrader
from .models import BinancePosition, PolymarketOrder, TradePair

logger = logging.getLogger(__name__)


class PositionManager:
    """Tracks open positions and manages lifecycle.
    
    Handles the creation, tracking, and closure of TradePairs,
    including automatic expiry handling and PnL calculation.
    
    Attributes:
        binance_trader: BinanceTrader instance for closing hedges
        on_position_closed: Callback when position is fully closed
    """
    
    def __init__(
        self,
        binance_trader: BinanceTrader,
        on_position_closed: Callable[[TradePair], Awaitable[None]] | None = None,
    ):
        """Initialize PositionManager.
        
        Args:
            binance_trader: BinanceTrader instance for closing hedges
            on_position_closed: Async callback invoked when position is fully closed
        """
        self._binance_trader = binance_trader
        self._on_position_closed = on_position_closed
        
        # Current open position (only one allowed at a time)
        self._open_position: TradePair | None = None
        
        # All trades (open and closed)
        self._all_trades: list[TradePair] = []
    
    def has_open_position(self) -> bool:
        """Check if a TradePair is currently open.
        
        Returns:
            True if a TradePair is currently open, False otherwise
        """
        return self._open_position is not None
    
    def get_open_position(self) -> TradePair | None:
        """Get the current open TradePair.
        
        Returns:
            Current open TradePair or None if no position is open
        """
        return self._open_position

    async def open_trade_pair(
        self,
        polymarket_order: PolymarketOrder,
        binance_position: BinancePosition | None,
        reference_entry_price: float | None = None,
    ) -> TradePair:
        """Create and track a new TradePair.
        
        Creates a TradePair with a unique UUID, sets entry and expiry times,
        and starts tracking the position.
        
        Args:
            polymarket_order: The filled Polymarket order
            binance_position: The Binance hedge position (None if hedge failed)
            
        Returns:
            The created TradePair with status "open"
        """
        trade_id = str(uuid.uuid4())
        entry_time = datetime.now(timezone.utc)
        expiry_time = entry_time + timedelta(minutes=5)
        
        trade_pair = TradePair(
            trade_id=trade_id,
            polymarket_order=polymarket_order,
            binance_position=binance_position,
            direction=polymarket_order.outcome,  # "UP" or "DOWN"
            entry_time=entry_time,
            expiry_time=expiry_time,
            status="open",
            polymarket_pnl=None,
            binance_pnl=None,
            total_pnl=None,
            reference_entry_price=reference_entry_price,
            reference_exit_price=None,
        )
        
        self._open_position = trade_pair
        self._all_trades.append(trade_pair)
        
        logger.info(
            f"Opened trade pair {trade_id}: "
            f"direction={trade_pair.direction}, "
            f"expiry={expiry_time.isoformat()}"
        )
        
        return trade_pair

    async def _calculate_dry_run_polymarket_pnl(self, trade_pair: TradePair) -> float | None:
        """Calculate dry-run Polymarket settlement from BTC price direction."""
        if not getattr(self._binance_trader, "dry_run", False):
            return trade_pair.polymarket_pnl

        if trade_pair.reference_entry_price is None:
            return trade_pair.polymarket_pnl

        shares_bought = trade_pair.polymarket_order.shares_bought
        if shares_bought is None:
            return trade_pair.polymarket_pnl

        try:
            exit_price = await self._binance_trader.get_current_price("BTCUSDT")
        except Exception as exc:
            logger.warning(
                f"Failed to get dry-run settlement price for trade {trade_pair.trade_id}: {exc}"
            )
            return trade_pair.polymarket_pnl

        trade_pair.reference_exit_price = exit_price

        if trade_pair.direction == "UP":
            won = exit_price > trade_pair.reference_entry_price
        elif trade_pair.direction == "DOWN":
            won = exit_price < trade_pair.reference_entry_price
        else:
            return trade_pair.polymarket_pnl

        stake_usd = trade_pair.polymarket_order.size
        payout = shares_bought if won else 0.0
        return round(payout - stake_usd, 2)
    
    async def close_trade_pair(self, trade_id: str) -> TradePair:
        """Close a TradePair and calculate PnL.
        
        Closes the Binance hedge position, calculates PnL for both
        Polymarket and Binance positions, and invokes the callback.
        
        Args:
            trade_id: The UUID of the TradePair to close
            
        Returns:
            The closed TradePair with PnL calculated
            
        Raises:
            ValueError: If trade_id not found or already closed
        """
        # Find the trade pair
        trade_pair = None
        for trade in self._all_trades:
            if trade.trade_id == trade_id:
                trade_pair = trade
                break
        
        if trade_pair is None:
            raise ValueError(f"Trade pair {trade_id} not found")
        
        if trade_pair.status == "closed":
            raise ValueError(f"Trade pair {trade_id} is already closed")
        
        # Update status to closing
        trade_pair.status = "closing"

        if trade_pair.polymarket_pnl is None:
            trade_pair.polymarket_pnl = await self._calculate_dry_run_polymarket_pnl(trade_pair)
        
        binance_pnl: float | None = None
        
        # Close Binance hedge position if it exists
        if trade_pair.binance_position is not None:
            try:
                closed_position = await self._binance_trader.close_position(
                    trade_pair.binance_position.position_id
                )
                binance_pnl = closed_position.pnl
                trade_pair.binance_position = closed_position
                
                logger.info(
                    f"Closed Binance hedge for trade {trade_id}: pnl={binance_pnl}"
                )
            except Exception as e:
                logger.error(f"Failed to close Binance position for trade {trade_id}: {e}")
                # Continue with closure even if Binance close fails
        
        # Calculate PnL
        # Note: Polymarket PnL would be calculated based on option settlement
        # For now, we set it to None as it depends on market outcome
        polymarket_pnl = trade_pair.polymarket_pnl
        
        trade_pair.binance_pnl = binance_pnl
        
        # Calculate total PnL if both components are available
        if polymarket_pnl is not None and binance_pnl is not None:
            trade_pair.total_pnl = polymarket_pnl + binance_pnl
        elif binance_pnl is not None:
            trade_pair.total_pnl = binance_pnl
        elif polymarket_pnl is not None:
            trade_pair.total_pnl = polymarket_pnl
        
        # Update status to closed
        trade_pair.status = "closed"
        
        # Clear open position if this was the open one
        if self._open_position and self._open_position.trade_id == trade_id:
            self._open_position = None
        
        logger.info(
            f"Closed trade pair {trade_id}: "
            f"polymarket_pnl={polymarket_pnl}, "
            f"binance_pnl={binance_pnl}, "
            f"total_pnl={trade_pair.total_pnl}"
        )
        
        # Invoke callback if set
        if self._on_position_closed is not None:
            try:
                await self._on_position_closed(trade_pair)
            except Exception as e:
                logger.error(f"Error in on_position_closed callback: {e}")
        
        return trade_pair
    
    async def check_expiries(self) -> None:
        """Check for expired positions and close hedges.
        
        Called periodically to check if the current open position
        has expired (current time >= expiry_time) and close it if so.
        """
        if self._open_position is None:
            return
        
        current_time = datetime.now(timezone.utc)
        
        if current_time >= self._open_position.expiry_time:
            logger.info(
                f"Trade pair {self._open_position.trade_id} has expired, closing..."
            )
            await self.close_trade_pair(self._open_position.trade_id)
    
    def get_all_trades(self) -> list[TradePair]:
        """Get all TradePairs (open and closed).
        
        Returns:
            List of all TradePairs tracked by this manager
        """
        return list(self._all_trades)
