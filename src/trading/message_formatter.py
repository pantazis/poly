"""Message formatting utilities for Telegram notifications.

This module provides the MessageFormatter class for formatting messages
with MarkdownV2 syntax, USD amounts, and timestamps for Telegram Bot API.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.trading.models import EntrySignal, TradePair


class MessageFormatter:
    """Utility class for formatting Telegram messages with MarkdownV2.
    
    Provides static methods for:
    - Escaping special characters for MarkdownV2
    - Formatting USD amounts with 2 decimals and thousand separators
    - Formatting timestamps in UTC format
    """
    
    # MarkdownV2 special characters that must be escaped
    MARKDOWN_SPECIAL_CHARS = r'_*[]()~`>#+-=|{}.!'
    
    @staticmethod
    def escape_markdown(text: str) -> str:
        """Escape special characters for Telegram MarkdownV2 format.
        
        Escapes the following characters: _ * [ ] ( ) ~ ` > # + - = | { } . !
        
        Args:
            text: The text to escape.
            
        Returns:
            The escaped text safe for MarkdownV2 parsing.
        """
        result = []
        for char in text:
            if char in MessageFormatter.MARKDOWN_SPECIAL_CHARS:
                result.append('\\')
            result.append(char)
        return ''.join(result)
    
    @staticmethod
    def format_usd(amount: float) -> str:
        """Format a USD amount with 2 decimal places and thousand separators.
        
        Examples:
            1234.5 -> "$1,234.50"
            -500.123 -> "-$500.12"
            1000000 -> "$1,000,000.00"
        
        Args:
            amount: The USD amount to format.
            
        Returns:
            Formatted string with $ prefix, 2 decimals, and comma separators.
        """
        if amount < 0:
            return f"-${abs(amount):,.2f}"
        return f"${amount:,.2f}"
    
    @staticmethod
    def format_timestamp(dt: datetime) -> str:
        """Format a datetime in UTC format for display.
        
        Format: "YYYY-MM-DD HH:MM:SS UTC"
        
        Args:
            dt: The datetime to format (assumed to be in UTC).
            
        Returns:
            Formatted timestamp string.
        """
        return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    
    @staticmethod
    def _mode_indicator(dry_run: bool) -> str:
        """Get the mode indicator prefix for messages.
        
        Args:
            dry_run: True for dry run mode, False for live mode.
            
        Returns:
            Bold mode indicator string: "*[DRY RUN]*" or "*[LIVE]*"
        """
        if dry_run:
            return r"*\[DRY RUN\]*"
        return r"*\[LIVE\]*"
    
    @staticmethod
    def format_startup(
        dry_run: bool,
        config: dict,
        timestamp: datetime,
    ) -> str:
        """Format a startup notification message.
        
        Args:
            dry_run: True for dry run mode, False for live mode.
            config: Configuration summary dict with keys:
                - bet_size: USDC bet size
                - hedge_size: Hedge position size
                - hedge_leverage: Leverage multiplier
                - max_daily_loss: Maximum daily loss limit
            timestamp: Startup timestamp.
            
        Returns:
            Formatted MarkdownV2 message string.
            
        Validates: Requirements 2.1, 10.2, 10.5
        """
        mode = MessageFormatter._mode_indicator(dry_run)
        ts = MessageFormatter.escape_markdown(MessageFormatter.format_timestamp(timestamp))
        
        bet_size = MessageFormatter.escape_markdown(MessageFormatter.format_usd(config.get("bet_size", 0)))
        hedge_size = MessageFormatter.escape_markdown(MessageFormatter.format_usd(config.get("hedge_size", 0)))
        hedge_leverage = config.get("hedge_leverage", 0)
        max_daily_loss = MessageFormatter.escape_markdown(MessageFormatter.format_usd(config.get("max_daily_loss", 0)))
        
        return (
            f"{mode} 🟢 *Bot Started*\n\n"
            f"⏰ {ts}\n\n"
            f"*Configuration:*\n"
            f"• Bet Size: {bet_size}\n"
            f"• Hedge Size: {hedge_size}\n"
            f"• Hedge Leverage: {hedge_leverage}x\n"
            f"• Max Daily Loss: {max_daily_loss}"
        )
    
    @staticmethod
    def format_shutdown(
        dry_run: bool,
        reason: str,
        trades: int,
        pnl: float,
        timestamp: datetime,
    ) -> str:
        """Format a shutdown notification message.
        
        Args:
            dry_run: True for dry run mode, False for live mode.
            reason: Shutdown reason (e.g., "graceful", "error", "signal").
            trades: Number of trades executed in the session.
            pnl: Total session PnL.
            timestamp: Shutdown timestamp.
            
        Returns:
            Formatted MarkdownV2 message string.
            
        Validates: Requirements 2.2, 10.2, 10.5
        """
        mode = MessageFormatter._mode_indicator(dry_run)
        ts = MessageFormatter.escape_markdown(MessageFormatter.format_timestamp(timestamp))
        escaped_reason = MessageFormatter.escape_markdown(reason)
        formatted_pnl = MessageFormatter.escape_markdown(MessageFormatter.format_usd(pnl))
        
        return (
            f"{mode} 🔴 *Bot Shutdown*\n\n"
            f"⏰ {ts}\n\n"
            f"*Reason:* {escaped_reason}\n\n"
            f"*Session Summary:*\n"
            f"• Trades: {trades}\n"
            f"• Total PnL: {formatted_pnl}"
        )
    
    @staticmethod
    def format_signal(
        dry_run: bool,
        signal: EntrySignal,
    ) -> str:
        """Format a signal detection notification message.
        
        Args:
            dry_run: True for dry run mode, False for live mode.
            signal: The detected entry signal.
            
        Returns:
            Formatted MarkdownV2 message string.
            
        Validates: Requirements 3.1, 10.2, 10.5
        """
        mode = MessageFormatter._mode_indicator(dry_run)
        ts = MessageFormatter.escape_markdown(MessageFormatter.format_timestamp(signal.timestamp))
        signal_type = MessageFormatter.escape_markdown(signal.signal_type)
        liquidation_usd = MessageFormatter.escape_markdown(MessageFormatter.format_usd(signal.liquidation_usd))
        
        return (
            f"{mode} 📊 *Signal Detected*\n\n"
            f"⏰ {ts}\n\n"
            f"*Type:* {signal_type}\n"
            f"*Total Liquidation:* {liquidation_usd}"
        )
    
    @staticmethod
    def format_signal_blocked(
        dry_run: bool,
        signal: EntrySignal,
        reason: str,
    ) -> str:
        """Format a blocked signal notification message.
        
        Args:
            dry_run: True for dry run mode, False for live mode.
            signal: The blocked entry signal.
            reason: Reason the signal was blocked.
            
        Returns:
            Formatted MarkdownV2 message string.
            
        Validates: Requirements 3.2, 10.2, 10.5
        """
        mode = MessageFormatter._mode_indicator(dry_run)
        ts = MessageFormatter.escape_markdown(MessageFormatter.format_timestamp(signal.timestamp))
        signal_type = MessageFormatter.escape_markdown(signal.signal_type)
        escaped_reason = MessageFormatter.escape_markdown(reason)
        
        return (
            f"{mode} ⚠️ *Signal Blocked*\n\n"
            f"⏰ {ts}\n\n"
            f"*Type:* {signal_type}\n"
            f"*Reason:* {escaped_reason}"
        )
    
    @staticmethod
    def format_trade_entry(
        dry_run: bool,
        trade_id: str,
        direction: str,
        price: float,
        size: float,
        reference_entry_price: float | None = None,
        shares_bought: float | None = None,
        max_profit: float | None = None,
        max_loss: float | None = None,
    ) -> str:
        """Format a trade entry notification message.
        
        Args:
            dry_run: True for dry run mode, False for live mode.
            trade_id: Unique trade identifier.
            direction: Trade direction ("UP" or "DOWN").
            price: Entry price.
            size: Bet size in USDC.
            
        Returns:
            Formatted MarkdownV2 message string.
            
        Validates: Requirements 4.1, 10.2, 10.5
        """
        mode = MessageFormatter._mode_indicator(dry_run)
        escaped_trade_id = MessageFormatter.escape_markdown(trade_id)
        escaped_direction = MessageFormatter.escape_markdown(direction)
        formatted_price = MessageFormatter.escape_markdown(f"{price:.4f}")
        formatted_size = MessageFormatter.escape_markdown(MessageFormatter.format_usd(size))
        stats_lines = ""

        if reference_entry_price is not None:
            stats_lines += (
                f"\n*Reference BTC Entry:* {MessageFormatter.escape_markdown(f'{reference_entry_price:,.2f}') }"
            )

        if shares_bought is not None:
            stats_lines += (
                f"\n*Shares:* {MessageFormatter.escape_markdown(f'{shares_bought:.4f}')}"
            )
        if max_profit is not None:
            stats_lines += (
                f"\n*Max Profit:* {MessageFormatter.escape_markdown(MessageFormatter.format_usd(max_profit))}"
            )
        if max_loss is not None:
            stats_lines += (
                f"\n*Max Loss:* {MessageFormatter.escape_markdown(MessageFormatter.format_usd(max_loss))}"
            )
        
        return (
            f"{mode} 💰 *Trade Entry*\n\n"
            f"*Trade ID:* `{escaped_trade_id}`\n"
            f"*Direction:* {escaped_direction}\n"
            f"*Entry Price:* {formatted_price}\n"
            f"*Bet Size:* {formatted_size}"
            f"{stats_lines}"
        )
    
    @staticmethod
    def format_hedge_opened(
        dry_run: bool,
        trade_id: str,
        side: str,
        entry_price: float,
        leverage: int,
    ) -> str:
        """Format a hedge opened notification message.
        
        Args:
            dry_run: True for dry run mode, False for live mode.
            trade_id: Unique trade identifier.
            side: Hedge side ("LONG" or "SHORT").
            entry_price: Hedge entry price.
            leverage: Leverage multiplier.
            
        Returns:
            Formatted MarkdownV2 message string.
            
        Validates: Requirements 4.2, 10.2, 10.5
        """
        mode = MessageFormatter._mode_indicator(dry_run)
        escaped_trade_id = MessageFormatter.escape_markdown(trade_id)
        escaped_side = MessageFormatter.escape_markdown(side)
        formatted_price = MessageFormatter.escape_markdown(f"{entry_price:.2f}")
        
        return (
            f"{mode} 💰 *Hedge Opened*\n\n"
            f"*Trade ID:* `{escaped_trade_id}`\n"
            f"*Side:* {escaped_side}\n"
            f"*Entry Price:* {formatted_price}\n"
            f"*Leverage:* {leverage}x"
        )
    
    @staticmethod
    def format_trade_closed(
        dry_run: bool,
        trade_id: str,
        polymarket_pnl: float | None,
        binance_pnl: float | None,
        total_pnl: float,
        daily_pnl: float,
        reference_entry_price: float | None = None,
        reference_exit_price: float | None = None,
    ) -> str:
        """Format a trade closed notification message.
        
        Args:
            dry_run: True for dry run mode, False for live mode.
            trade_id: Unique trade identifier.
            polymarket_pnl: PnL from Polymarket bet (None if not available).
            binance_pnl: PnL from Binance hedge (None if not available).
            total_pnl: Combined total PnL.
            daily_pnl: Running daily PnL total.
            
        Returns:
            Formatted MarkdownV2 message string.
            
        Validates: Requirements 4.3, 10.2, 10.5
        """
        mode = MessageFormatter._mode_indicator(dry_run)
        escaped_trade_id = MessageFormatter.escape_markdown(trade_id)
        
        # Format PnL values
        poly_pnl_str = MessageFormatter.escape_markdown(
            MessageFormatter.format_usd(polymarket_pnl) if polymarket_pnl is not None else "N/A"
        )
        binance_pnl_str = MessageFormatter.escape_markdown(
            MessageFormatter.format_usd(binance_pnl) if binance_pnl is not None else "N/A"
        )
        total_pnl_str = MessageFormatter.escape_markdown(MessageFormatter.format_usd(total_pnl))
        daily_pnl_str = MessageFormatter.escape_markdown(MessageFormatter.format_usd(daily_pnl))
        reference_lines = ""

        if reference_entry_price is not None:
            reference_lines += (
                f"*Reference BTC Entry:* {MessageFormatter.escape_markdown(f'{reference_entry_price:,.2f}')}\n"
            )
        if reference_exit_price is not None:
            reference_lines += (
                f"*Reference BTC Exit:* {MessageFormatter.escape_markdown(f'{reference_exit_price:,.2f}')}\n"
            )
        
        # Add emoji based on total PnL
        pnl_emoji = "🟢" if total_pnl >= 0 else "🔴"
        
        return (
            f"{mode} 💰 *Trade Closed* {pnl_emoji}\n\n"
            f"*Trade ID:* `{escaped_trade_id}`\n\n"
            f"{reference_lines if reference_lines else ''}"
            f"*PnL Breakdown:*\n"
            f"• Polymarket: {poly_pnl_str}\n"
            f"• Binance: {binance_pnl_str}\n"
            f"• *Total:* {total_pnl_str}\n\n"
            f"*Daily PnL:* {daily_pnl_str}"
        )
    
    @staticmethod
    def format_error(
        dry_run: bool,
        error_type: str,
        exchange: str,
        message: str,
        timestamp: datetime,
    ) -> str:
        """Format an error notification message.
        
        Args:
            dry_run: True for dry run mode, False for live mode.
            error_type: Type of error (e.g., "API Error", "Connection Error").
            exchange: Exchange name ("polymarket" or "binance").
            message: Error message details.
            timestamp: Error timestamp.
            
        Returns:
            Formatted MarkdownV2 message string.
            
        Validates: Requirements 5.1, 10.2, 10.5
        """
        mode = MessageFormatter._mode_indicator(dry_run)
        ts = MessageFormatter.escape_markdown(MessageFormatter.format_timestamp(timestamp))
        escaped_error_type = MessageFormatter.escape_markdown(error_type)
        escaped_exchange = MessageFormatter.escape_markdown(exchange)
        escaped_message = MessageFormatter.escape_markdown(message)
        
        return (
            f"{mode} 🔴 *Error*\n\n"
            f"⏰ {ts}\n\n"
            f"*Type:* {escaped_error_type}\n"
            f"*Exchange:* {escaped_exchange}\n"
            f"*Message:* {escaped_message}"
        )
    
    @staticmethod
    def format_risk_alert(
        dry_run: bool,
        alert_type: str,
        details: str,
        is_critical: bool = False,
    ) -> str:
        """Format a risk alert notification message.
        
        Args:
            dry_run: True for dry run mode, False for live mode.
            alert_type: Type of risk alert (e.g., "Daily Loss Limit", "Position Close Failed").
            details: Alert details.
            is_critical: True for critical alerts (🚨), False for warnings (⚠️).
            
        Returns:
            Formatted MarkdownV2 message string.
            
        Validates: Requirements 5.2, 5.3, 10.2, 10.5
        """
        mode = MessageFormatter._mode_indicator(dry_run)
        emoji = "🚨" if is_critical else "⚠️"
        alert_label = "CRITICAL ALERT" if is_critical else "Risk Alert"
        escaped_alert_type = MessageFormatter.escape_markdown(alert_type)
        escaped_details = MessageFormatter.escape_markdown(details)
        
        return (
            f"{mode} {emoji} *{alert_label}*\n\n"
            f"*Type:* {escaped_alert_type}\n"
            f"*Details:* {escaped_details}"
        )

    @staticmethod
    def format_pnl_summary(
        start_date,
        end_date,
        total_pnl: float,
        trade_count: int,
        win_count: int,
        loss_count: int,
        win_rate: float,
    ) -> str:
        """Format a PnL summary response message.
        
        Args:
            start_date: Start date of the period.
            end_date: End date of the period.
            total_pnl: Total PnL for the period.
            trade_count: Number of trades in the period.
            win_count: Number of winning trades.
            loss_count: Number of losing trades.
            win_rate: Win rate as a decimal (0.0 to 1.0).
            
        Returns:
            Formatted MarkdownV2 message string.
            
        Validates: Requirements 7.6
        """
        # Format date range
        if start_date == end_date:
            date_range_str = start_date.strftime("%Y-%m-%d")
        else:
            date_range_str = f"{start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}"
        
        escaped_date_range = MessageFormatter.escape_markdown(date_range_str)
        formatted_pnl = MessageFormatter.escape_markdown(MessageFormatter.format_usd(total_pnl))
        win_rate_pct = MessageFormatter.escape_markdown(f"{win_rate * 100:.1f}%")
        
        # Add emoji based on total PnL
        pnl_emoji = "🟢" if total_pnl >= 0 else "🔴"
        
        return (
            f"📊 *PnL Summary* {pnl_emoji}\n\n"
            f"*Period:* {escaped_date_range}\n\n"
            f"*Results:*\n"
            f"• Total PnL: {formatted_pnl}\n"
            f"• Trades: {trade_count}\n"
            f"• Wins: {win_count}\n"
            f"• Losses: {loss_count}\n"
            f"• Win Rate: {win_rate_pct}"
        )

    @staticmethod
    def format_status(
        dry_run: bool,
        running: bool,
        open_position: TradePair | None,
        daily_pnl: float,
        daily_limit_remaining: float,
        uptime: timedelta,
    ) -> str:
        """Format a bot status response message.
        
        Args:
            dry_run: True for dry run mode, False for live mode.
            running: True if bot is running, False if stopped.
            open_position: Current open TradePair or None.
            daily_pnl: Current daily realized PnL.
            daily_limit_remaining: Remaining daily loss limit.
            uptime: Bot uptime duration.
            
        Returns:
            Formatted MarkdownV2 message string.
            
        Validates: Requirements 8.1, 8.2
        """
        mode = MessageFormatter._mode_indicator(dry_run)
        
        # Format running state
        state_emoji = "🟢" if running else "🔴"
        state_text = "Running" if running else "Stopped"
        
        # Format open position
        if open_position is not None:
            entry_time_str = MessageFormatter.escape_markdown(
                MessageFormatter.format_timestamp(open_position.entry_time)
            )
            position_text = (
                f"*Direction:* {MessageFormatter.escape_markdown(open_position.direction)}\n"
                f"*Entry Time:* {entry_time_str}"
            )
        else:
            position_text = "None"
        
        # Format PnL values
        daily_pnl_str = MessageFormatter.escape_markdown(MessageFormatter.format_usd(daily_pnl))
        daily_limit_str = MessageFormatter.escape_markdown(MessageFormatter.format_usd(daily_limit_remaining))
        
        # Format uptime
        total_seconds = int(uptime.total_seconds())
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        uptime_str = f"{hours}h {minutes}m {seconds}s"
        
        return (
            f"{mode} 📊 *Bot Status*\n\n"
            f"*State:* {state_emoji} {state_text}\n\n"
            f"*Open Position:*\n{position_text}\n\n"
            f"*Daily PnL:* {daily_pnl_str}\n"
            f"*Loss Limit Remaining:* {daily_limit_str}\n\n"
            f"*Uptime:* {uptime_str}"
        )

    @staticmethod
    def format_balance(
        dry_run: bool,
        polymarket_balance: float | None,
        binance_balance: float | None,
        polymarket_error: str | None,
        binance_error: str | None,
    ) -> str:
        """Format a balance response message.
        
        Args:
            dry_run: True for dry run mode, False for live mode.
            polymarket_balance: Polymarket USDC balance or None if failed.
            binance_balance: Binance available margin balance or None if failed.
            polymarket_error: Error message if Polymarket query failed.
            binance_error: Error message if Binance query failed.
            
        Returns:
            Formatted MarkdownV2 message string.
            
        Validates: Requirements 9.1, 9.2, 9.3
        """
        mode = MessageFormatter._mode_indicator(dry_run)
        
        # Format Polymarket balance
        if polymarket_balance is not None:
            poly_str = MessageFormatter.escape_markdown(MessageFormatter.format_usd(polymarket_balance))
        else:
            error_msg = polymarket_error or "Unknown error"
            poly_str = f"❌ Error: {MessageFormatter.escape_markdown(error_msg)}"
        
        # Format Binance balance
        if binance_balance is not None:
            binance_str = MessageFormatter.escape_markdown(MessageFormatter.format_usd(binance_balance))
        else:
            error_msg = binance_error or "Unknown error"
            binance_str = f"❌ Error: {MessageFormatter.escape_markdown(error_msg)}"
        
        # Calculate total if both balances are available
        if polymarket_balance is not None and binance_balance is not None:
            total = polymarket_balance + binance_balance
            total_str = MessageFormatter.escape_markdown(MessageFormatter.format_usd(total))
        else:
            total_str = "N/A \\(partial data\\)"
        
        return (
            f"{mode} 💰 *Account Balances*\n\n"
            f"*Polymarket USDC:* {poly_str}\n"
            f"*Binance Margin:* {binance_str}\n\n"
            f"*Total:* {total_str}"
        )
