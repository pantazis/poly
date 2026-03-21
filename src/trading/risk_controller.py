"""Risk controller for enforcing position limits and risk parameters.

This module provides the RiskController class that enforces trading limits
including daily loss limits, concurrent position limits, and balance checks.
"""

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.trading.binance_trader import BinanceTrader
    from src.trading.polymarket_connector import PolymarketConnector

logger = logging.getLogger(__name__)


class RiskController:
    """Enforces position limits and risk parameters.
    
    Tracks daily PnL, enforces loss limits, and validates that sufficient
    balance/margin exists before allowing new trades.
    
    Attributes:
        max_daily_loss: Maximum daily realized loss in USD (positive value)
        max_concurrent_positions: Maximum number of open Trade_Pairs allowed
    """
    
    def __init__(
        self,
        max_daily_loss: float = 100.0,
        max_concurrent_positions: int = 1,
        polymarket_connector: "PolymarketConnector | None" = None,
        binance_trader: "BinanceTrader | None" = None,
    ):
        """Initialize the RiskController.
        
        Args:
            max_daily_loss: Maximum daily realized loss in USD (default: $100)
            max_concurrent_positions: Maximum open Trade_Pairs (default: 1)
            polymarket_connector: PolymarketConnector for balance checks
            binance_trader: BinanceTrader for margin checks
        """
        self._max_daily_loss = max_daily_loss
        self._max_concurrent_positions = max_concurrent_positions
        self._polymarket_connector = polymarket_connector
        self._binance_trader = binance_trader
        
        # Track daily realized PnL (negative = loss)
        self._daily_pnl: float = 0.0
    
    def record_pnl(self, pnl: float) -> None:
        """Record realized PnL from a closed position.
        
        Args:
            pnl: Realized PnL in USD (positive = profit, negative = loss)
        """
        self._daily_pnl += pnl
        logger.info(f"Recorded PnL: ${pnl:.2f}, Daily total: ${self._daily_pnl:.2f}")
    
    def get_daily_pnl(self) -> float:
        """Get current daily realized PnL.
        
        Returns:
            Current daily realized PnL in USD
        """
        return self._daily_pnl
    
    def is_daily_limit_reached(self) -> bool:
        """Check if daily loss limit has been reached.
        
        Returns:
            True if daily realized loss >= max_daily_loss
        """
        # Loss is represented as negative PnL
        # If daily_pnl is -100 and max_daily_loss is 100, limit is reached
        return self._daily_pnl <= -self._max_daily_loss
    
    async def can_open_position(
        self,
        bet_size: float,
        hedge_margin_required: float,
        current_open_positions: int,
    ) -> tuple[bool, str]:
        """Check if a new position can be opened.
        
        Validates:
        1. Daily loss limit not reached
        2. Max concurrent positions not exceeded
        3. Polymarket balance >= bet_size
        4. Binance margin >= hedge_margin_required
        
        Args:
            bet_size: USDC amount for Polymarket bet
            hedge_margin_required: USDT margin needed for Binance hedge
            current_open_positions: Number of currently open positions
            
        Returns:
            Tuple of (allowed, reason) where reason explains rejection
        """
        # Check 1: Daily loss limit
        if self.is_daily_limit_reached():
            reason = f"Daily loss limit reached (${self._max_daily_loss:.2f})"
            logger.warning(f"Trade blocked: {reason}")
            return (False, reason)
        
        # Check 2: Max concurrent positions
        if current_open_positions >= self._max_concurrent_positions:
            reason = f"Max concurrent positions reached ({self._max_concurrent_positions})"
            logger.warning(f"Trade blocked: {reason}")
            return (False, reason)
        
        # Check 3: Polymarket balance
        if self._polymarket_connector is not None:
            polymarket_balance = await self._polymarket_connector.get_balance()
            if polymarket_balance < bet_size:
                reason = f"Insufficient Polymarket balance: ${polymarket_balance:.2f} < ${bet_size:.2f}"
                logger.warning(f"Trade blocked: {reason}")
                return (False, reason)
        
        # Check 4: Binance margin
        if self._binance_trader is not None:
            binance_margin = await self._binance_trader.get_available_margin()
            if binance_margin < hedge_margin_required:
                reason = f"Insufficient Binance margin: ${binance_margin:.2f} < ${hedge_margin_required:.2f}"
                logger.warning(f"Trade blocked: {reason}")
                return (False, reason)
        
        logger.info("Position check passed: trade allowed")
        return (True, "")
    
    def reset_daily_pnl(self) -> None:
        """Reset daily PnL counter.
        
        Should be called at UTC midnight to start fresh daily tracking.
        """
        logger.info(f"Resetting daily PnL from ${self._daily_pnl:.2f} to $0.00")
        self._daily_pnl = 0.0
