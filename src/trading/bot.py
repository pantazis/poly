"""TradingBot - Main orchestrator that coordinates all trading components.

This module provides the TradingBot class that wires together all trading
components and manages the complete trade lifecycle from signal detection
through position closure.
"""

import asyncio
import logging
import signal
import sys
from datetime import datetime

from src.collector import LiquidationCollector

from .binance_trader import BinanceTrader
from .config import TradingConfig
from .models import BinancePosition, EntrySignal, TradePair
from .pnl_aggregator import PnLAggregator
from .polymarket_connector import PolymarketConnector
from .position_manager import PositionManager
from .risk_controller import RiskController
from .signal_detector import SignalDetector
from .telegram_command_handler import TelegramCommandHandler
from .telegram_notifier import TelegramNotifier
from .trade_logger import TradeLogger

logger = logging.getLogger(__name__)


class TradingBot:
    """Main orchestrator that coordinates all trading components.
    
    Wires together SignalDetector, PolymarketConnector, BinanceTrader,
    PositionManager, RiskController, and TradeLogger to execute the
    liquidation-based trading strategy.
    
    Event flow:
    SignalDetector → RiskController → PolymarketConnector → 
    BinanceTrader → PositionManager → TradeLogger
    """
    
    def __init__(self, config: TradingConfig, collector: LiquidationCollector):
        """Initialize the TradingBot with all components.
        
        Args:
            config: Trading configuration with all parameters
            collector: LiquidationCollector instance for signal detection
        """
        self._config = config
        self._collector = collector
        self._running = False
        self._shutdown_event = asyncio.Event()
        
        # Initialize TradeLogger
        self._trade_logger = TradeLogger(
            log_dir=config.log_dir,
            flush_interval_seconds=5.0,
        )
        
        # Initialize PolymarketConnector
        self._polymarket_connector = PolymarketConnector(
            private_key=config.polymarket_private_key,
            dry_run=config.dry_run,
        )
        
        # Initialize BinanceTrader
        self._binance_trader = BinanceTrader(
            api_key=config.binance_api_key,
            api_secret=config.binance_api_secret,
            dry_run=config.dry_run,
        )

        # Initialize PositionManager with on_position_closed callback
        self._position_manager = PositionManager(
            binance_trader=self._binance_trader,
            on_position_closed=self._handle_position_closed,
        )
        
        # Initialize RiskController with connector references
        self._risk_controller = RiskController(
            max_daily_loss=config.max_daily_loss,
            max_concurrent_positions=config.max_concurrent_positions,
            polymarket_connector=self._polymarket_connector,
            binance_trader=self._binance_trader,
        )
        
        # Initialize SignalDetector with on_signal callback
        self._signal_detector = SignalDetector(
            collector=collector,
            threshold_min=config.entry_threshold_min,
            threshold_max=config.entry_threshold_max,
            window_minutes=config.liquidation_window_minutes,
            on_signal=self._handle_signal,
        )
        
        # Initialize PnLAggregator
        self._pnl_aggregator = PnLAggregator(log_dir=config.log_dir)
        
        # Initialize Telegram components
        self._telegram_notifier: TelegramNotifier | None = None
        telegram_enabled = config.telegram_enabled
        
        if telegram_enabled:
            # Check if token and chat_id are provided
            if not config.telegram_token:
                logger.warning(
                    "Telegram enabled but TELEGRAM_TOKEN is empty, disabling notifications"
                )
                telegram_enabled = False
            elif not config.telegram_chat_id:
                logger.warning(
                    "Telegram enabled but TELEGRAM_CHAT_ID is empty, disabling notifications"
                )
                telegram_enabled = False
            else:
                # Create TelegramNotifier with valid configuration
                self._telegram_notifier = TelegramNotifier(
                    token=config.telegram_token,
                    chat_id=config.telegram_chat_id,
                    dry_run=config.dry_run,
                    enabled=True,
                )
        
        # Background tasks
        self._health_check_task: asyncio.Task | None = None
        self._expiry_check_task: asyncio.Task | None = None
        self._data_flush_task: asyncio.Task | None = None
        
        # Telegram command handler (initialized in start())
        self._telegram_command_handler: TelegramCommandHandler | None = None
        self._start_time: datetime | None = None
    
    async def start(self) -> None:
        """Start the trading bot.
        
        1. Verify exchange connectivity
        2. Send startup notification (or error notification if connectivity fails)
        3. Start signal detection
        4. Start TelegramCommandHandler polling
        5. Set up periodic tasks (health checks, expiry checks, data flush)
        6. Block until shutdown signal
        
        Raises:
            SystemExit: If exchange connectivity fails
        """
        logger.info("Starting Trading Bot")
        logger.info(f"Dry run mode: {self._config.dry_run}")
        logger.info(f"Bet size: ${self._config.bet_size:.2f}")
        logger.info(f"Hedge leverage: {self._config.hedge_leverage}x")
        logger.info(f"Max daily loss: ${self._config.max_daily_loss:.2f}")
        
        # Verify Polymarket connectivity
        logger.info("Verifying Polymarket API connectivity...")
        polymarket_connected = await self._polymarket_connector.connect()
        if not polymarket_connected:
            logger.error("Failed to connect to Polymarket API. Exiting.")
            # Send error notification before exit
            if self._telegram_notifier:
                await self._telegram_notifier.send_error(
                    error_type="connectivity_failure",
                    exchange="polymarket",
                    message="Failed to connect to Polymarket API during startup",
                )
            sys.exit(1)
        
        # Verify Binance connectivity
        logger.info("Verifying Binance API connectivity...")
        binance_connected = await self._binance_trader.connect()
        if not binance_connected:
            logger.error("Failed to connect to Binance API. Exiting.")
            # Send error notification before exit
            if self._telegram_notifier:
                await self._telegram_notifier.send_error(
                    error_type="connectivity_failure",
                    exchange="binance",
                    message="Failed to connect to Binance API during startup",
                )
            sys.exit(1)
        
        logger.info("Exchange connectivity verified successfully")
        
        # Record start time for uptime tracking
        self._start_time = datetime.utcnow()
        
        # Send startup notification
        if self._telegram_notifier:
            config_summary = {
                "bet_size": self._config.bet_size,
                "hedge_size": self._config.hedge_size,
                "hedge_leverage": self._config.hedge_leverage,
                "max_daily_loss": self._config.max_daily_loss,
            }
            await self._telegram_notifier.send_startup(
                config_summary=config_summary,
                timestamp=self._start_time,
            )
        
        self._running = True
        
        # Set up signal handlers (Unix only)
        if sys.platform != "win32":
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(
                    sig, 
                    lambda: asyncio.create_task(self.shutdown())
                )
        
        # Start signal detection
        await self._signal_detector.start()
        
        # Start TelegramCommandHandler polling
        if self._telegram_notifier:
            self._telegram_command_handler = TelegramCommandHandler(
                token=self._config.telegram_token,
                chat_id=self._config.telegram_chat_id,
                notifier=self._telegram_notifier,
                pnl_aggregator=self._pnl_aggregator,
                risk_controller=self._risk_controller,
                position_manager=self._position_manager,
                binance_trader=self._binance_trader,
                polymarket_connector=self._polymarket_connector,
                dry_run=self._config.dry_run,
                start_time=self._start_time,
            )
            await self._telegram_command_handler.start()
        
        # Start periodic tasks
        self._health_check_task = asyncio.create_task(self._periodic_health_check())
        self._expiry_check_task = asyncio.create_task(self._periodic_expiry_check())
        self._data_flush_task = asyncio.create_task(self._periodic_data_flush())
        
        logger.info("Trading Bot started successfully")
        
        # Block until shutdown signal
        try:
            await self._shutdown_event.wait()
        except asyncio.CancelledError:
            pass
    
    async def shutdown(self) -> None:
        """Graceful shutdown within 30 seconds.
        
        1. Stop accepting new signals
        2. Stop TelegramCommandHandler polling
        3. Close open Binance positions
        4. Flush trade logs
        5. Send shutdown notification
        6. Close exchange connections
        7. Close TelegramNotifier
        """
        if not self._running:
            return
        
        logger.info("Shutdown signal received")
        self._running = False
        
        # 1. Stop accepting new signals (immediate)
        logger.info("Stopping signal detection...")
        await self._signal_detector.stop()
        
        # 2. Stop TelegramCommandHandler polling
        if self._telegram_command_handler:
            logger.info("Stopping Telegram command handler...")
            try:
                await self._telegram_command_handler.stop()
            except Exception as e:
                logger.error(f"Error stopping Telegram command handler: {e}")
        
        # Cancel periodic tasks
        for task in [self._health_check_task, self._expiry_check_task, self._data_flush_task]:
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        
        # 3. Close open Binance positions (20s timeout)
        open_position = self._position_manager.get_open_position()
        if open_position and open_position.binance_position:
            logger.info(f"Closing open position {open_position.trade_id}...")
            try:
                await asyncio.wait_for(
                    self._position_manager.close_trade_pair(open_position.trade_id),
                    timeout=20.0
                )
                logger.info(f"Closed hedge position {open_position.trade_id}")
            except asyncio.TimeoutError:
                logger.error(
                    f"Failed to close position {open_position.trade_id} within timeout. "
                    f"MANUAL INTERVENTION REQUIRED: {open_position.binance_position}"
                )
                # Send critical alert for failed position close
                if self._telegram_notifier:
                    await self._telegram_notifier.send_risk_alert(
                        alert_type="position_close_failed",
                        details=f"Failed to close position {open_position.trade_id} during shutdown. "
                                f"Manual intervention required: {open_position.binance_position}",
                    )
            except Exception as e:
                logger.error(
                    f"Error closing position {open_position.trade_id}: {e}. "
                    f"Manual intervention may be required."
                )
                # Send critical alert for failed position close
                if self._telegram_notifier:
                    await self._telegram_notifier.send_risk_alert(
                        alert_type="position_close_failed",
                        details=f"Error closing position {open_position.trade_id}: {e}. "
                                f"Manual intervention may be required.",
                    )
        
        # 4. Flush trade logs (8s timeout)
        logger.info("Flushing trade logs...")
        try:
            await asyncio.wait_for(self._trade_logger.close(), timeout=8.0)
            logger.info("Trade logs flushed successfully")
        except asyncio.TimeoutError:
            logger.error("Trade log flush timed out, some logs may be lost")
        except Exception as e:
            logger.error(f"Error flushing trade logs: {e}")
        
        # 5. Send shutdown notification
        if self._telegram_notifier:
            # Calculate session trades and PnL
            session_trades = len(self._position_manager.get_all_trades())
            session_pnl = self._risk_controller.get_daily_pnl()
            
            logger.info("Sending shutdown notification...")
            try:
                await self._telegram_notifier.send_shutdown(
                    reason="graceful",
                    session_trades=session_trades,
                    session_pnl=session_pnl,
                    timestamp=datetime.utcnow(),
                )
            except Exception as e:
                logger.error(f"Error sending shutdown notification: {e}")
        
        # 6. Close exchange connections
        logger.info("Closing exchange connections...")
        try:
            await self._polymarket_connector.close()
        except Exception as e:
            logger.error(f"Error closing Polymarket connector: {e}")
        
        try:
            await self._binance_trader.close()
        except Exception as e:
            logger.error(f"Error closing Binance trader: {e}")
        
        # 7. Close TelegramNotifier
        if self._telegram_notifier:
            logger.info("Closing Telegram notifier...")
            try:
                await self._telegram_notifier.close()
            except Exception as e:
                logger.error(f"Error closing Telegram notifier: {e}")
        
        logger.info("Shutdown complete")
        self._shutdown_event.set()

    async def _handle_signal(self, signal: EntrySignal) -> None:
        """Process entry signal through the trading pipeline.
        
        1. Send signal notification
        2. Check risk_controller.can_open_position()
        3. If blocked, send blocked notification, log and return
        4. Log signal via trade_logger
        5. Place Polymarket order
        6. If order fills, call _handle_polymarket_fill()
        7. If order fails/cancels, log and return
        
        Args:
            signal: The entry signal from SignalDetector
        """
        logger.info(
            f"Processing signal: {signal.signal_type}, "
            f"total=${signal.liquidation_usd:,.0f}"
        )
        
        # Send signal notification
        if self._telegram_notifier:
            await self._telegram_notifier.send_signal(signal)
        
        # Calculate required margin for hedge
        # hedge_margin = hedge_size / leverage (approximate)
        hedge_margin_required = self._config.hedge_size / self._config.hedge_leverage
        
        # Check if we can open a position
        current_open = 1 if self._position_manager.has_open_position() else 0
        can_open, reason = await self._risk_controller.can_open_position(
            bet_size=self._config.bet_size,
            hedge_margin_required=hedge_margin_required,
            current_open_positions=current_open,
        )
        
        if not can_open:
            logger.warning(f"Signal blocked by risk controller: {reason}")
            # Send blocked signal notification
            if self._telegram_notifier:
                await self._telegram_notifier.send_signal_blocked(signal, reason)
            return
        
        # Log the signal
        await self._trade_logger.log_signal(signal, is_dry_run=self._config.dry_run)
        
        # Determine Polymarket outcome based on signal type
        # Long liquidations (price going DOWN) → Buy "DOWN"
        # Short liquidations (price going UP) → Buy "UP"
        if signal.signal_type == "long_liquidation":
            outcome = "DOWN"
        else:  # short_liquidation
            outcome = "UP"
        
        logger.info(f"Placing Polymarket order: {outcome}, size=${self._config.bet_size:.2f}")
        
        # Place Polymarket order
        try:
            order = await self._polymarket_connector.place_order(
                outcome=outcome,
                size=self._config.bet_size,
                discount_percent=self._config.discount_percent,
                timeout_seconds=30.0,
            )
        except Exception as e:
            logger.error(f"Error placing Polymarket order: {e}")
            # Send error notification for Polymarket API failure (Requirement 5.1)
            if self._telegram_notifier:
                await self._telegram_notifier.send_error(
                    error_type="order_placement_failed",
                    exchange="polymarket",
                    message=str(e),
                )
            return
        
        # Check order status
        if order.status == "filled":
            logger.info(
                f"Polymarket order filled: {order.outcome} at {order.fill_price:.4f}"
            )
            await self._handle_polymarket_fill(order)
        else:
            logger.warning(
                f"Polymarket order not filled: status={order.status}, "
                f"order_id={order.order_id}"
            )
    
    async def _handle_polymarket_fill(self, order) -> None:
        """Handle Polymarket order fill by optionally opening Binance hedge.
        
        1. If hedge_enabled, determine Binance hedge direction (UP → SHORT, DOWN → LONG)
        2. If hedge_enabled, open Binance hedge position
        3. Create TradePair via position_manager
        4. Log order fills
        5. Set signal_detector.set_position_open(True)
        
        Args:
            order: The filled PolymarketOrder
        """
        binance_position: BinancePosition | None = None
        
        # Only open hedge if enabled
        if self._config.hedge_enabled:
            # Determine hedge direction
            # UP on Polymarket → SHORT on Binance
            # DOWN on Polymarket → LONG on Binance
            if order.outcome == "UP":
                hedge_side = "SHORT"
            else:  # DOWN
                hedge_side = "LONG"
            
            logger.info(
                f"Opening Binance hedge: {hedge_side}, "
                f"size=${self._config.hedge_size:.2f}, "
                f"leverage={self._config.hedge_leverage}x"
            )
            
            # Open Binance hedge position
            try:
                binance_position = await self._binance_trader.open_position(
                    side=hedge_side,
                    size_usd=self._config.hedge_size,
                    leverage=self._config.hedge_leverage,
                    max_retries=3,
                )
                logger.info(
                    f"Binance hedge opened: {binance_position.side} "
                    f"at {binance_position.entry_price:.2f}"
                )
            except Exception as e:
                logger.error(f"Failed to open Binance hedge: {e}")
                # Send error notification for Binance API failure (Requirement 5.1)
                if self._telegram_notifier:
                    await self._telegram_notifier.send_error(
                        error_type="hedge_open_failed",
                        exchange="binance",
                        message=str(e),
                    )
                # Continue with unhedged position
        else:
            logger.info("Hedging disabled, skipping Binance position")
        
        # Create TradePair
        trade_pair = await self._position_manager.open_trade_pair(
            polymarket_order=order,
            binance_position=binance_position,
        )
        
        # Log order fills
        await self._trade_logger.log_order_filled(
            trade_id=trade_pair.trade_id,
            exchange="polymarket",
            side=order.outcome,
            size=order.size,
            fill_price=order.fill_price or order.price,
            is_dry_run=self._config.dry_run,
        )
        
        # Send trade entry notification (Requirement 4.1)
        if self._telegram_notifier:
            await self._telegram_notifier.send_trade_entry(
                trade_id=trade_pair.trade_id,
                direction=order.outcome,
                entry_price=order.fill_price or order.price,
                bet_size=order.size,
            )
        
        if binance_position:
            await self._trade_logger.log_order_filled(
                trade_id=trade_pair.trade_id,
                exchange="binance",
                side=binance_position.side,
                size=self._config.hedge_size,
                fill_price=binance_position.entry_price,
                is_dry_run=self._config.dry_run,
            )
            
            # Send hedge opened notification (Requirement 4.2)
            if self._telegram_notifier:
                await self._telegram_notifier.send_hedge_opened(
                    trade_id=trade_pair.trade_id,
                    side=binance_position.side,
                    entry_price=binance_position.entry_price,
                    leverage=self._config.hedge_leverage,
                )
        
        # Block new signals while position is open
        self._signal_detector.set_position_open(True)
        
        logger.info(
            f"Trade pair opened: {trade_pair.trade_id}, "
            f"direction={trade_pair.direction}, "
            f"expiry={trade_pair.expiry_time.isoformat()}"
        )
    
    async def _handle_position_closed(self, trade_pair: TradePair) -> None:
        """Callback when position is fully closed.
        
        1. Record PnL via risk_controller
        2. Log position close via trade_logger
        3. Send trade close notification
        4. Set signal_detector.set_position_open(False)
        
        Args:
            trade_pair: The closed TradePair
        """
        # Record PnL
        if trade_pair.total_pnl is not None:
            self._risk_controller.record_pnl(trade_pair.total_pnl)
        elif trade_pair.binance_pnl is not None:
            self._risk_controller.record_pnl(trade_pair.binance_pnl)
        
        # Log position close
        if trade_pair.binance_position and trade_pair.binance_pnl is not None:
            await self._trade_logger.log_position_closed(
                trade_id=trade_pair.trade_id,
                exchange="binance",
                pnl=trade_pair.binance_pnl,
                is_dry_run=self._config.dry_run,
            )
        
        # Send trade close notification (Requirement 4.3)
        if self._telegram_notifier:
            daily_pnl = self._risk_controller.get_daily_pnl()
            await self._telegram_notifier.send_trade_closed(
                trade_id=trade_pair.trade_id,
                polymarket_pnl=trade_pair.polymarket_pnl,
                binance_pnl=trade_pair.binance_pnl,
                total_pnl=trade_pair.total_pnl or 0.0,
                daily_pnl=daily_pnl,
            )
        
        # Enable new signals
        self._signal_detector.set_position_open(False)
        
        logger.info(
            f"Trade pair closed: {trade_pair.trade_id}, "
            f"total_pnl=${trade_pair.total_pnl or 0:.2f}, "
            f"daily_pnl=${self._risk_controller.get_daily_pnl():.2f}"
        )

    async def _periodic_health_check(self) -> None:
        """Periodic health check task (every 30 seconds)."""
        while self._running:
            await asyncio.sleep(30)
            try:
                # Log current status
                daily_pnl = self._risk_controller.get_daily_pnl()
                has_position = self._position_manager.has_open_position()
                
                logger.debug(
                    f"Health check: daily_pnl=${daily_pnl:.2f}, "
                    f"position_open={has_position}"
                )
                
                # Check if daily limit reached
                if self._risk_controller.is_daily_limit_reached():
                    logger.warning(
                        f"Daily loss limit reached: ${daily_pnl:.2f}. "
                        f"New signals blocked until UTC midnight."
                    )
                    # Send risk alert for daily loss limit (Requirement 5.2)
                    if self._telegram_notifier:
                        await self._telegram_notifier.send_risk_alert(
                            alert_type="daily_loss_limit_reached",
                            details=f"Daily loss limit reached: ${daily_pnl:.2f}. "
                                    f"New signals blocked until UTC midnight.",
                        )
            except Exception as e:
                logger.error(f"Error in health check: {e}")
    
    async def _periodic_expiry_check(self) -> None:
        """Periodic expiry check task (every 1 second)."""
        while self._running:
            await asyncio.sleep(1)
            try:
                await self._position_manager.check_expiries()
            except Exception as e:
                logger.error(f"Error in expiry check: {e}")
    
    async def _periodic_data_flush(self) -> None:
        """Periodic data flush task (every 5 seconds)."""
        while self._running:
            await asyncio.sleep(5)
            try:
                await self._trade_logger.flush()
            except Exception as e:
                logger.error(f"Error in data flush: {e}")
