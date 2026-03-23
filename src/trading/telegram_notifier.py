"""Telegram Bot API integration for sending notifications.

This module provides the TelegramNotifier class for sending formatted
messages to Telegram with deduplication and retry logic.
"""

import asyncio
import hashlib
import logging
from datetime import datetime
from typing import TYPE_CHECKING

import aiohttp

if TYPE_CHECKING:
    from src.trading.models import EntrySignal

from .message_formatter import MessageFormatter

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Sends formatted messages to Telegram with deduplication.
    
    Handles Telegram Bot API communication with:
    - Retry logic with exponential backoff for network errors
    - Rate limit handling (429 responses)
    - Message truncation for long messages
    - Automatic disabling on invalid token/chat errors
    
    Attributes:
        token: Telegram Bot API token
        chat_id: Target chat ID for messages
        dry_run: If True, messages include [DRY RUN] indicator
        enabled: If False, no messages are sent
    """
    
    # Telegram message length limit
    MAX_MESSAGE_LENGTH = 4096
    
    # Retry configuration
    MAX_RETRIES = 3
    INITIAL_BACKOFF_SECONDS = 1.0
    
    # Telegram API base URL
    API_BASE_URL = "https://api.telegram.org"
    
    def __init__(
        self,
        token: str,
        chat_id: str,
        dry_run: bool,
        enabled: bool = True,
    ) -> None:
        """Initialize TelegramNotifier.
        
        Args:
            token: Telegram Bot API token
            chat_id: Target chat ID for messages
            dry_run: If True, messages include [DRY RUN] indicator
            enabled: If False, no messages are sent
        """
        self.token = token
        self.chat_id = chat_id
        self.dry_run = dry_run
        self.enabled = enabled
        
        self._session: aiohttp.ClientSession | None = None
        
        # Deduplication cache: message_hash -> sent_at timestamp
        self._dedup_cache: dict[str, datetime] = {}
        self._dedup_window_seconds = 60
        self._dedup_cleanup_interval_seconds = 300  # 5 minutes
        self._last_cleanup: datetime = datetime.utcnow()
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session
    
    def _truncate_message(self, text: str) -> str:
        """Truncate message to Telegram's maximum length.
        
        Args:
            text: Message text to truncate
            
        Returns:
            Truncated message with "..." suffix if needed
        """
        if len(text) <= self.MAX_MESSAGE_LENGTH:
            return text
        
        # Leave room for "..." suffix
        return text[:self.MAX_MESSAGE_LENGTH - 3] + "..."
    
    def _get_message_hash(self, text: str) -> str:
        """Generate hash for message deduplication.
        
        Args:
            text: Message text to hash
            
        Returns:
            MD5 hash of the message
        """
        return hashlib.md5(text.encode("utf-8")).hexdigest()
    
    def _is_duplicate(self, text: str) -> bool:
        """Check if message is a duplicate within the deduplication window.
        
        Args:
            text: Message text to check
            
        Returns:
            True if identical message was sent within 60 seconds
        """
        now = datetime.utcnow()
        
        # Cleanup old entries periodically
        if (now - self._last_cleanup).total_seconds() > self._dedup_cleanup_interval_seconds:
            self._cleanup_dedup_cache()
            self._last_cleanup = now
        
        message_hash = self._get_message_hash(text)
        
        if message_hash in self._dedup_cache:
            sent_at = self._dedup_cache[message_hash]
            if (now - sent_at).total_seconds() < self._dedup_window_seconds:
                return True
        
        return False
    
    def _record_message(self, text: str) -> None:
        """Record message in deduplication cache.
        
        Args:
            text: Message text to record
        """
        message_hash = self._get_message_hash(text)
        self._dedup_cache[message_hash] = datetime.utcnow()
    
    def _cleanup_dedup_cache(self) -> None:
        """Remove entries older than 5 minutes from deduplication cache."""
        now = datetime.utcnow()
        expired_hashes = [
            h for h, sent_at in self._dedup_cache.items()
            if (now - sent_at).total_seconds() > self._dedup_cleanup_interval_seconds
        ]
        for h in expired_hashes:
            del self._dedup_cache[h]
        
        if expired_hashes:
            logger.debug(f"Cleaned up {len(expired_hashes)} expired dedup entries")
    
    async def _send_message(self, text: str) -> bool:
        """Send message to Telegram using Bot API.
        
        Implements retry logic with exponential backoff for network errors.
        Handles rate limits by waiting retry_after seconds.
        Disables notifier on invalid token (401) or chat not found (400).
        
        Args:
            text: Message text to send (MarkdownV2 format)
            
        Returns:
            True if message sent successfully, False otherwise
        """
        if not self.enabled:
            logger.debug("Telegram notifier disabled, skipping message")
            return False
        
        # Truncate if needed
        text = self._truncate_message(text)
        
        # Check for duplicates
        if self._is_duplicate(text):
            logger.debug("Skipping duplicate message")
            return False
        
        url = f"{self.API_BASE_URL}/bot{self.token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "MarkdownV2",
        }
        
        session = await self._get_session()
        backoff = self.INITIAL_BACKOFF_SECONDS
        
        for attempt in range(self.MAX_RETRIES):
            try:
                async with session.post(url, json=payload) as response:
                    if response.status == 200:
                        self._record_message(text)
                        logger.debug("Telegram message sent successfully")
                        return True
                    
                    # Handle rate limiting
                    if response.status == 429:
                        data = await response.json()
                        retry_after = data.get("parameters", {}).get("retry_after", backoff)
                        logger.warning(f"Telegram rate limited, waiting {retry_after}s")
                        await asyncio.sleep(retry_after)
                        continue
                    
                    # Handle invalid token
                    if response.status == 401:
                        logger.error("Invalid Telegram token, disabling notifier")
                        self.enabled = False
                        return False
                    
                    # Handle chat not found
                    if response.status == 400:
                        data = await response.json()
                        error_desc = data.get("description", "")
                        if "chat not found" in error_desc.lower():
                            logger.error(f"Telegram chat not found: {self.chat_id}, disabling notifier")
                            self.enabled = False
                            return False
                        # Other 400 errors - log and retry
                        logger.warning(f"Telegram API error (400): {error_desc}")
                    
                    # Other errors - log and retry
                    logger.warning(
                        f"Telegram API error (attempt {attempt + 1}/{self.MAX_RETRIES}): "
                        f"status={response.status}"
                    )
                    
            except aiohttp.ClientError as e:
                logger.warning(
                    f"Telegram network error (attempt {attempt + 1}/{self.MAX_RETRIES}): {e}"
                )
            except asyncio.TimeoutError:
                logger.warning(
                    f"Telegram timeout (attempt {attempt + 1}/{self.MAX_RETRIES})"
                )
            
            # Exponential backoff before retry
            if attempt < self.MAX_RETRIES - 1:
                logger.debug(f"Retrying in {backoff}s...")
                await asyncio.sleep(backoff)
                backoff *= 2  # Exponential backoff: 1s, 2s, 4s
        
        logger.error(f"Failed to send Telegram message after {self.MAX_RETRIES} attempts")
        return False
    
    async def send_startup(
        self,
        config_summary: dict,
        timestamp: datetime,
    ) -> None:
        """Send bot startup notification.
        
        Args:
            config_summary: Dict with bet_size, hedge_size, hedge_leverage, max_daily_loss
            timestamp: Startup timestamp
        """
        message = MessageFormatter.format_startup(
            dry_run=self.dry_run,
            config=config_summary,
            timestamp=timestamp,
        )
        await self._send_message(message)
    
    async def send_shutdown(
        self,
        reason: str,
        session_trades: int,
        session_pnl: float,
        timestamp: datetime,
    ) -> None:
        """Send bot shutdown notification.
        
        Args:
            reason: Shutdown reason (graceful, error, signal)
            session_trades: Number of trades in session
            session_pnl: Total session PnL
            timestamp: Shutdown timestamp
        """
        message = MessageFormatter.format_shutdown(
            dry_run=self.dry_run,
            reason=reason,
            trades=session_trades,
            pnl=session_pnl,
            timestamp=timestamp,
        )
        await self._send_message(message)
    
    async def send_signal(
        self,
        signal: "EntrySignal",
    ) -> None:
        """Send signal detection notification.
        
        Args:
            signal: The detected entry signal
        """
        message = MessageFormatter.format_signal(
            dry_run=self.dry_run,
            signal=signal,
        )
        await self._send_message(message)
    
    async def send_signal_blocked(
        self,
        signal: "EntrySignal",
        reason: str,
    ) -> None:
        """Send blocked signal notification.
        
        Args:
            signal: The blocked entry signal
            reason: Reason the signal was blocked
        """
        message = MessageFormatter.format_signal_blocked(
            dry_run=self.dry_run,
            signal=signal,
            reason=reason,
        )
        await self._send_message(message)
    
    async def send_trade_entry(
        self,
        trade_id: str,
        direction: str,
        entry_price: float,
        bet_size: float,
        reference_entry_price: float | None = None,
        shares_bought: float | None = None,
        max_profit: float | None = None,
        max_loss: float | None = None,
    ) -> None:
        """Send trade entry notification.
        
        Args:
            trade_id: Unique trade identifier
            direction: Trade direction (UP/DOWN)
            entry_price: Entry price
            bet_size: Bet size in USDC
        """
        message = MessageFormatter.format_trade_entry(
            dry_run=self.dry_run,
            trade_id=trade_id,
            direction=direction,
            price=entry_price,
            size=bet_size,
            reference_entry_price=reference_entry_price,
            shares_bought=shares_bought,
            max_profit=max_profit,
            max_loss=max_loss,
        )
        await self._send_message(message)
    
    async def send_hedge_opened(
        self,
        trade_id: str,
        side: str,
        entry_price: float,
        leverage: int,
    ) -> None:
        """Send hedge opened notification.
        
        Args:
            trade_id: Unique trade identifier
            side: Hedge side (LONG/SHORT)
            entry_price: Hedge entry price
            leverage: Leverage multiplier
        """
        message = MessageFormatter.format_hedge_opened(
            dry_run=self.dry_run,
            trade_id=trade_id,
            side=side,
            entry_price=entry_price,
            leverage=leverage,
        )
        await self._send_message(message)
    
    async def send_trade_closed(
        self,
        trade_id: str,
        polymarket_pnl: float | None,
        binance_pnl: float | None,
        total_pnl: float,
        daily_pnl: float,
        reference_entry_price: float | None = None,
        reference_exit_price: float | None = None,
    ) -> None:
        """Send trade closed notification.
        
        Args:
            trade_id: Unique trade identifier
            polymarket_pnl: PnL from Polymarket bet
            binance_pnl: PnL from Binance hedge
            total_pnl: Combined total PnL
            daily_pnl: Running daily PnL total
        """
        message = MessageFormatter.format_trade_closed(
            dry_run=self.dry_run,
            trade_id=trade_id,
            polymarket_pnl=polymarket_pnl,
            binance_pnl=binance_pnl,
            total_pnl=total_pnl,
            daily_pnl=daily_pnl,
            reference_entry_price=reference_entry_price,
            reference_exit_price=reference_exit_price,
        )
        await self._send_message(message)
    
    async def send_error(
        self,
        error_type: str,
        exchange: str,
        message: str,
    ) -> None:
        """Send error notification.
        
        Args:
            error_type: Type of error
            exchange: Exchange name (polymarket/binance)
            message: Error message details
        """
        formatted_message = MessageFormatter.format_error(
            dry_run=self.dry_run,
            error_type=error_type,
            exchange=exchange,
            message=message,
            timestamp=datetime.utcnow(),
        )
        await self._send_message(formatted_message)
    
    async def send_risk_alert(
        self,
        alert_type: str,
        details: str,
    ) -> None:
        """Send risk alert notification.
        
        Args:
            alert_type: Type of risk alert
            details: Alert details
        """
        # Determine if critical based on alert type
        is_critical = "failed" in alert_type.lower() or "critical" in alert_type.lower()
        
        message = MessageFormatter.format_risk_alert(
            dry_run=self.dry_run,
            alert_type=alert_type,
            details=details,
            is_critical=is_critical,
        )
        await self._send_message(message)
    
    async def close(self) -> None:
        """Close the aiohttp session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
