"""Telegram command handler for interactive bot commands.

This module provides the TelegramCommandHandler class for processing
incoming Telegram commands via long polling.
"""

import asyncio
import logging
from datetime import date, datetime

import aiohttp

from .binance_trader import BinanceTrader
from .message_formatter import MessageFormatter
from .pnl_aggregator import PnLAggregator
from .polymarket_connector import PolymarketConnector
from .position_manager import PositionManager
from .risk_controller import RiskController
from .telegram_notifier import TelegramNotifier

logger = logging.getLogger(__name__)


class TelegramCommandHandler:
    """Handles incoming Telegram commands via long polling.
    
    Processes commands like /pnl, /status, and /balance by polling
    the Telegram Bot API for updates and responding accordingly.
    
    Attributes:
        token: Telegram Bot API token
        chat_id: Authorized chat ID for commands
        notifier: TelegramNotifier for sending responses
        pnl_aggregator: PnLAggregator for PnL queries
        risk_controller: RiskController for status queries
        position_manager: PositionManager for position queries
        binance_trader: BinanceTrader for balance queries
        polymarket_connector: PolymarketConnector for balance queries
        dry_run: If True, return simulated balances
        start_time: Bot start time for uptime calculation
    """
    
    # Telegram API base URL
    API_BASE_URL = "https://api.telegram.org"
    
    # Polling configuration
    POLL_TIMEOUT_SECONDS = 30
    POLL_INTERVAL_SECONDS = 1
    
    def __init__(
        self,
        token: str,
        chat_id: str,
        notifier: TelegramNotifier,
        pnl_aggregator: PnLAggregator,
        risk_controller: RiskController,
        position_manager: PositionManager,
        binance_trader: BinanceTrader,
        polymarket_connector: PolymarketConnector,
        dry_run: bool,
        start_time: datetime,
    ) -> None:
        """Initialize TelegramCommandHandler.
        
        Args:
            token: Telegram Bot API token
            chat_id: Authorized chat ID for commands
            notifier: TelegramNotifier for sending responses
            pnl_aggregator: PnLAggregator for PnL queries
            risk_controller: RiskController for status queries
            position_manager: PositionManager for position queries
            binance_trader: BinanceTrader for balance queries
            polymarket_connector: PolymarketConnector for balance queries
            dry_run: If True, return simulated balances
            start_time: Bot start time for uptime calculation
        """
        self.token = token
        self.chat_id = chat_id
        self.notifier = notifier
        self.pnl_aggregator = pnl_aggregator
        self.risk_controller = risk_controller
        self.position_manager = position_manager
        self.binance_trader = binance_trader
        self.polymarket_connector = polymarket_connector
        self.dry_run = dry_run
        self.start_time = start_time
        
        self._session: aiohttp.ClientSession | None = None
        self._running: bool = False
        self._last_update_id: int = 0
        self._poll_task: asyncio.Task | None = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session
    
    async def start(self) -> None:
        """Start the long polling loop.
        
        Begins polling the Telegram Bot API for updates in a background task.
        The polling loop continues until stop() is called.
        """
        if self._running:
            logger.warning("TelegramCommandHandler is already running")
            return
        
        self._running = True
        logger.info("Starting Telegram command handler polling")
        
        # Start polling in a background task
        self._poll_task = asyncio.create_task(self._polling_loop())
    
    async def stop(self) -> None:
        """Stop the polling loop gracefully.
        
        Sets the running flag to False and waits for the polling task
        to complete. Also closes the aiohttp session.
        """
        if not self._running:
            logger.warning("TelegramCommandHandler is not running")
            return
        
        logger.info("Stopping Telegram command handler polling")
        self._running = False
        
        # Wait for the polling task to complete
        if self._poll_task is not None:
            try:
                # Give the task a chance to finish gracefully
                await asyncio.wait_for(self._poll_task, timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning("Polling task did not stop gracefully, cancelling")
                self._poll_task.cancel()
                try:
                    await self._poll_task
                except asyncio.CancelledError:
                    pass
            self._poll_task = None
        
        # Close the session
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
        
        logger.info("Telegram command handler stopped")
    
    async def _polling_loop(self) -> None:
        """Main polling loop that fetches and processes updates.
        
        Continuously polls the Telegram API for new updates using
        long polling. Processes each update and handles any errors
        gracefully to keep the loop running.
        """
        while self._running:
            try:
                updates = await self._get_updates()
                
                for update in updates:
                    await self._process_update(update)
                
            except asyncio.CancelledError:
                logger.debug("Polling loop cancelled")
                break
            except aiohttp.ClientError as e:
                logger.warning(f"Network error in polling loop: {e}")
                await asyncio.sleep(self.POLL_INTERVAL_SECONDS)
            except Exception as e:
                logger.error(f"Error in polling loop: {e}")
                await asyncio.sleep(self.POLL_INTERVAL_SECONDS)
    
    async def _get_updates(self) -> list[dict]:
        """Fetch updates from Telegram API using long polling.
        
        Uses the getUpdates endpoint with a timeout to wait for new
        messages. Tracks the last update_id to avoid processing
        duplicate updates.
        
        Returns:
            List of update objects from Telegram API
        """
        session = await self._get_session()
        
        url = f"{self.API_BASE_URL}/bot{self.token}/getUpdates"
        params = {
            "timeout": self.POLL_TIMEOUT_SECONDS,
            "allowed_updates": ["message"],
        }
        
        # Only fetch updates after the last processed one
        if self._last_update_id > 0:
            params["offset"] = self._last_update_id + 1
        
        try:
            async with session.get(
                url,
                params=params,
                timeout=aiohttp.ClientTimeout(total=self.POLL_TIMEOUT_SECONDS + 10)
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("ok"):
                        updates = data.get("result", [])
                        
                        # Update last_update_id to avoid duplicates
                        if updates:
                            self._last_update_id = max(
                                u.get("update_id", 0) for u in updates
                            )
                        
                        return updates
                    else:
                        logger.warning(f"Telegram API error: {data.get('description')}")
                else:
                    logger.warning(f"Telegram API returned status {response.status}")
        except asyncio.TimeoutError:
            # Timeout is expected with long polling, just continue
            pass
        
        return []
    
    async def _process_update(self, update: dict) -> None:
        """Process a single update from Telegram.
        
        Extracts the message and command from the update, validates
        the chat ID, and dispatches to the appropriate handler.
        
        Args:
            update: Update object from Telegram API
        """
        message = update.get("message", {})
        chat = message.get("chat", {})
        chat_id = str(chat.get("id", ""))
        text = message.get("text", "")
        
        # Only process messages from authorized chat
        if chat_id != self.chat_id:
            logger.debug(f"Ignoring message from unauthorized chat: {chat_id}")
            return
        
        # Check if it's a command
        if not text.startswith("/"):
            return
        
        # Parse command and arguments
        parts = text.split()
        command = parts[0].lower()
        args = parts[1:] if len(parts) > 1 else []
        
        logger.info(f"Received command: {command} with args: {args}")
        
        # Dispatch to appropriate handler
        try:
            if command == "/pnl":
                response = await self._handle_pnl_command(args)
            elif command == "/status":
                response = await self._handle_status_command()
            elif command == "/balance":
                response = await self._handle_balance_command()
            else:
                response = "Unknown command. Available commands: /pnl, /status, /balance"
            
            # Send response
            await self._send_response(response)
            
        except Exception as e:
            logger.error(f"Error handling command {command}: {e}")
            await self._send_response(f"Error processing command: {str(e)}")
    
    async def _send_response(self, text: str, use_markdown: bool = True) -> None:
        """Send a response message to the chat.
        
        Uses the Telegram Bot API sendMessage endpoint to send
        a response back to the authorized chat.
        
        Args:
            text: Response text to send
            use_markdown: If True, use MarkdownV2 parse mode
        """
        session = await self._get_session()
        
        url = f"{self.API_BASE_URL}/bot{self.token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
        }
        
        if use_markdown:
            payload["parse_mode"] = "MarkdownV2"
        
        try:
            async with session.post(url, json=payload) as response:
                if response.status != 200:
                    data = await response.json()
                    error_desc = data.get('description', '')
                    logger.warning(f"Failed to send response: {error_desc}")
                    
                    # If MarkdownV2 parsing failed, retry without parse_mode
                    if use_markdown and "can't parse entities" in error_desc:
                        logger.info("Retrying without MarkdownV2 formatting")
                        await self._send_response(text, use_markdown=False)
        except Exception as e:
            logger.error(f"Error sending response: {e}")
    
    async def _handle_pnl_command(self, args: list[str]) -> str:
        """Handle /pnl command.
        
        Args:
            args: Command arguments (empty for today, single date, or date range)
            
        Returns:
            Formatted PnL summary response
        """
        usage_help = (
            "📖 *Usage:*\n"
            "• `/pnl` \\- Today's PnL\n"
            "• `/pnl YYYY\\-MM\\-DD` \\- PnL for specific date\n"
            "• `/pnl YYYY\\-MM\\-DD YYYY\\-MM\\-DD` \\- PnL for date range"
        )
        
        try:
            if len(args) == 0:
                # No arguments - today's PnL
                target_date = date.today()
                summary = self.pnl_aggregator.get_pnl_for_date(target_date)
            elif len(args) == 1:
                # Single date
                target_date = datetime.strptime(args[0], "%Y-%m-%d").date()
                summary = self.pnl_aggregator.get_pnl_for_date(target_date)
            elif len(args) == 2:
                # Date range
                start_date = datetime.strptime(args[0], "%Y-%m-%d").date()
                end_date = datetime.strptime(args[1], "%Y-%m-%d").date()
                
                if end_date < start_date:
                    return "❌ End date must be after start date\\.\n\n" + usage_help
                
                summary = self.pnl_aggregator.get_pnl_for_range(start_date, end_date)
            else:
                return "❌ Too many arguments\\.\n\n" + usage_help
            
            # Check if no trades found
            if summary.trade_count == 0:
                return MessageFormatter.escape_markdown("No trades found for the specified period")
            
            # Format and return the response
            return MessageFormatter.format_pnl_summary(
                start_date=summary.start_date,
                end_date=summary.end_date,
                total_pnl=summary.total_pnl,
                trade_count=summary.trade_count,
                win_count=summary.win_count,
                loss_count=summary.loss_count,
                win_rate=summary.win_rate,
            )
            
        except ValueError:
            return "❌ Invalid date format\\. Use YYYY\\-MM\\-DD\\.\n\n" + usage_help
    
    async def _handle_status_command(self) -> str:
        """Handle /status command.
        
        Queries bot state, open position, daily PnL, and uptime.
        Formats response with mode indicator.
        
        Returns:
            Formatted bot status response
            
        Validates: Requirements 8.1, 8.2
        """
        # Get current running state (handler is running if we're processing commands)
        running = self._running
        
        # Get open position from position manager
        open_position = self.position_manager.get_open_position()
        
        # Get daily PnL from risk controller
        daily_pnl = self.risk_controller.get_daily_pnl()
        
        # Calculate daily loss limit remaining
        # max_daily_loss is stored as positive, daily_pnl is negative for losses
        max_daily_loss = self.risk_controller._max_daily_loss
        # If daily_pnl is -50 and max_daily_loss is 100, remaining is 100 - 50 = 50
        daily_limit_remaining = max_daily_loss + daily_pnl  # daily_pnl is negative for losses
        
        # Calculate uptime
        current_time = datetime.now(self.start_time.tzinfo) if self.start_time.tzinfo else datetime.now()
        uptime = current_time - self.start_time
        
        # Format and return the response
        return MessageFormatter.format_status(
            dry_run=self.dry_run,
            running=running,
            open_position=open_position,
            daily_pnl=daily_pnl,
            daily_limit_remaining=daily_limit_remaining,
            uptime=uptime,
        )
    
    async def _handle_balance_command(self) -> str:
        """Handle /balance command.
        
        Queries Polymarket and Binance balances. In dry_run mode,
        returns simulated/mock balances. Handles partial failures
        by showing successful balance and error indicator for failed exchange.
        
        Returns:
            Formatted balance response
            
        Validates: Requirements 9.1, 9.2, 9.3
        """
        polymarket_balance: float | None = None
        binance_balance: float | None = None
        polymarket_error: str | None = None
        binance_error: str | None = None
        
        if self.dry_run:
            # Return simulated balances in dry run mode
            polymarket_balance = 10000.0
            binance_balance = 10000.0
        else:
            # Query actual balances from exchanges
            # Query Polymarket balance
            try:
                polymarket_balance = await self.polymarket_connector.get_balance()
            except Exception as e:
                logger.error(f"Failed to get Polymarket balance: {e}")
                polymarket_error = str(e)
            
            # Query Binance balance
            try:
                binance_balance = await self.binance_trader.get_available_margin()
            except Exception as e:
                logger.error(f"Failed to get Binance balance: {e}")
                binance_error = str(e)
        
        # Format and return the response
        return MessageFormatter.format_balance(
            dry_run=self.dry_run,
            polymarket_balance=polymarket_balance,
            binance_balance=binance_balance,
            polymarket_error=polymarket_error,
            binance_error=binance_error,
        )
