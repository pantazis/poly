"""Unit tests for MessageFormatter class."""

import pytest
from datetime import datetime

from src.trading.message_formatter import MessageFormatter


class TestEscapeMarkdown:
    """Tests for escape_markdown() method."""
    
    def test_escapes_underscore(self):
        """Underscores should be escaped."""
        assert MessageFormatter.escape_markdown("hello_world") == r"hello\_world"
    
    def test_escapes_asterisk(self):
        """Asterisks should be escaped."""
        assert MessageFormatter.escape_markdown("*bold*") == r"\*bold\*"
    
    def test_escapes_brackets(self):
        """Square brackets should be escaped."""
        assert MessageFormatter.escape_markdown("[link]") == r"\[link\]"
    
    def test_escapes_parentheses(self):
        """Parentheses should be escaped."""
        assert MessageFormatter.escape_markdown("(text)") == r"\(text\)"
    
    def test_escapes_tilde(self):
        """Tildes should be escaped."""
        assert MessageFormatter.escape_markdown("~strikethrough~") == r"\~strikethrough\~"
    
    def test_escapes_backtick(self):
        """Backticks should be escaped."""
        assert MessageFormatter.escape_markdown("`code`") == r"\`code\`"
    
    def test_escapes_greater_than(self):
        """Greater than signs should be escaped."""
        assert MessageFormatter.escape_markdown(">quote") == r"\>quote"
    
    def test_escapes_hash(self):
        """Hash signs should be escaped."""
        assert MessageFormatter.escape_markdown("#heading") == r"\#heading"
    
    def test_escapes_plus(self):
        """Plus signs should be escaped."""
        assert MessageFormatter.escape_markdown("+1") == r"\+1"
    
    def test_escapes_minus(self):
        """Minus signs should be escaped."""
        assert MessageFormatter.escape_markdown("-1") == r"\-1"
    
    def test_escapes_equals(self):
        """Equals signs should be escaped."""
        assert MessageFormatter.escape_markdown("a=b") == r"a\=b"
    
    def test_escapes_pipe(self):
        """Pipe characters should be escaped."""
        assert MessageFormatter.escape_markdown("a|b") == r"a\|b"
    
    def test_escapes_curly_braces(self):
        """Curly braces should be escaped."""
        assert MessageFormatter.escape_markdown("{json}") == r"\{json\}"
    
    def test_escapes_dot(self):
        """Dots should be escaped."""
        assert MessageFormatter.escape_markdown("1.2.3") == r"1\.2\.3"
    
    def test_escapes_exclamation(self):
        """Exclamation marks should be escaped."""
        assert MessageFormatter.escape_markdown("Hello!") == r"Hello\!"
    
    def test_plain_text_unchanged(self):
        """Plain text without special chars should be unchanged."""
        assert MessageFormatter.escape_markdown("hello world") == "hello world"
    
    def test_empty_string(self):
        """Empty string should return empty string."""
        assert MessageFormatter.escape_markdown("") == ""
    
    def test_all_special_chars(self):
        """All special characters should be escaped."""
        input_text = "_*[]()~`>#+-=|{}.!"
        expected = r"\_\*\[\]\(\)\~\`\>\#\+\-\=\|\{\}\.\!"
        assert MessageFormatter.escape_markdown(input_text) == expected


class TestFormatUsd:
    """Tests for format_usd() method."""
    
    def test_positive_amount(self):
        """Positive amounts should have $ prefix."""
        assert MessageFormatter.format_usd(100.00) == "$100.00"
    
    def test_negative_amount(self):
        """Negative amounts should have -$ prefix."""
        assert MessageFormatter.format_usd(-100.00) == "-$100.00"
    
    def test_zero(self):
        """Zero should format as $0.00."""
        assert MessageFormatter.format_usd(0) == "$0.00"
    
    def test_two_decimal_places(self):
        """Should always show exactly 2 decimal places."""
        assert MessageFormatter.format_usd(100) == "$100.00"
        assert MessageFormatter.format_usd(100.1) == "$100.10"
        assert MessageFormatter.format_usd(100.123) == "$100.12"
    
    def test_thousand_separator(self):
        """Should use comma as thousand separator."""
        assert MessageFormatter.format_usd(1000) == "$1,000.00"
        assert MessageFormatter.format_usd(1000000) == "$1,000,000.00"
    
    def test_large_negative_with_separator(self):
        """Large negative amounts should have separators."""
        assert MessageFormatter.format_usd(-1234567.89) == "-$1,234,567.89"
    
    def test_small_decimal(self):
        """Small decimals should round to 2 places."""
        assert MessageFormatter.format_usd(0.01) == "$0.01"
        assert MessageFormatter.format_usd(0.001) == "$0.00"


class TestFormatTimestamp:
    """Tests for format_timestamp() method."""
    
    def test_basic_format(self):
        """Should format as YYYY-MM-DD HH:MM:SS UTC."""
        dt = datetime(2024, 1, 15, 10, 30, 45)
        assert MessageFormatter.format_timestamp(dt) == "2024-01-15 10:30:45 UTC"
    
    def test_midnight(self):
        """Midnight should show 00:00:00."""
        dt = datetime(2024, 12, 31, 0, 0, 0)
        assert MessageFormatter.format_timestamp(dt) == "2024-12-31 00:00:00 UTC"
    
    def test_end_of_day(self):
        """End of day should show 23:59:59."""
        dt = datetime(2024, 6, 15, 23, 59, 59)
        assert MessageFormatter.format_timestamp(dt) == "2024-06-15 23:59:59 UTC"
    
    def test_single_digit_padding(self):
        """Single digit months/days/hours should be zero-padded."""
        dt = datetime(2024, 1, 5, 9, 5, 3)
        assert MessageFormatter.format_timestamp(dt) == "2024-01-05 09:05:03 UTC"


class TestModeIndicator:
    """Tests for _mode_indicator() method."""
    
    def test_dry_run_mode(self):
        """Dry run mode should return [DRY RUN] in bold."""
        result = MessageFormatter._mode_indicator(True)
        assert result == r"*\[DRY RUN\]*"
    
    def test_live_mode(self):
        """Live mode should return [LIVE] in bold."""
        result = MessageFormatter._mode_indicator(False)
        assert result == r"*\[LIVE\]*"


class TestFormatStartup:
    """Tests for format_startup() method."""
    
    def test_contains_mode_indicator_dry_run(self):
        """Startup message should start with mode indicator."""
        config = {"bet_size": 100, "hedge_size": 50, "hedge_leverage": 3, "max_daily_loss": 200}
        ts = datetime(2024, 1, 15, 10, 30, 0)
        result = MessageFormatter.format_startup(True, config, ts)
        assert result.startswith(r"*\[DRY RUN\]*")
    
    def test_contains_mode_indicator_live(self):
        """Startup message should start with [LIVE] in live mode."""
        config = {"bet_size": 100, "hedge_size": 50, "hedge_leverage": 3, "max_daily_loss": 200}
        ts = datetime(2024, 1, 15, 10, 30, 0)
        result = MessageFormatter.format_startup(False, config, ts)
        assert result.startswith(r"*\[LIVE\]*")
    
    def test_contains_startup_emoji(self):
        """Startup message should contain green emoji."""
        config = {"bet_size": 100, "hedge_size": 50, "hedge_leverage": 3, "max_daily_loss": 200}
        ts = datetime(2024, 1, 15, 10, 30, 0)
        result = MessageFormatter.format_startup(True, config, ts)
        assert "🟢" in result
    
    def test_contains_timestamp(self):
        """Startup message should contain formatted timestamp."""
        config = {"bet_size": 100, "hedge_size": 50, "hedge_leverage": 3, "max_daily_loss": 200}
        ts = datetime(2024, 1, 15, 10, 30, 0)
        result = MessageFormatter.format_startup(True, config, ts)
        assert "2024\\-01\\-15 10:30:00 UTC" in result
    
    def test_contains_config_values(self):
        """Startup message should contain all config values."""
        config = {"bet_size": 1000, "hedge_size": 500, "hedge_leverage": 3, "max_daily_loss": 200}
        ts = datetime(2024, 1, 15, 10, 30, 0)
        result = MessageFormatter.format_startup(True, config, ts)
        assert "$1,000\\.00" in result  # bet_size
        assert "$500\\.00" in result  # hedge_size
        assert "3x" in result  # hedge_leverage
        assert "$200\\.00" in result  # max_daily_loss


class TestFormatShutdown:
    """Tests for format_shutdown() method."""
    
    def test_contains_mode_indicator(self):
        """Shutdown message should start with mode indicator."""
        ts = datetime(2024, 1, 15, 10, 30, 0)
        result = MessageFormatter.format_shutdown(True, "graceful", 5, 150.50, ts)
        assert result.startswith(r"*\[DRY RUN\]*")
    
    def test_contains_shutdown_emoji(self):
        """Shutdown message should contain red emoji."""
        ts = datetime(2024, 1, 15, 10, 30, 0)
        result = MessageFormatter.format_shutdown(True, "graceful", 5, 150.50, ts)
        assert "🔴" in result
    
    def test_contains_reason(self):
        """Shutdown message should contain the reason."""
        ts = datetime(2024, 1, 15, 10, 30, 0)
        result = MessageFormatter.format_shutdown(True, "graceful", 5, 150.50, ts)
        assert "graceful" in result
    
    def test_contains_session_summary(self):
        """Shutdown message should contain trades and PnL."""
        ts = datetime(2024, 1, 15, 10, 30, 0)
        result = MessageFormatter.format_shutdown(True, "graceful", 5, 150.50, ts)
        assert "5" in result  # trades
        assert "$150\\.50" in result  # pnl


class TestFormatSignal:
    """Tests for format_signal() method."""
    
    def test_contains_mode_indicator(self):
        """Signal message should start with mode indicator."""
        from src.trading.models import EntrySignal
        signal = EntrySignal(
            signal_type="long_liquidation",
            liquidation_usd=50000.0,
            timestamp=datetime(2024, 1, 15, 10, 30, 0),
            dominant_side="long_liquidated",
            long_usd=40000.0,
            short_usd=10000.0
        )
        result = MessageFormatter.format_signal(True, signal)
        assert result.startswith(r"*\[DRY RUN\]*")
    
    def test_contains_signal_emoji(self):
        """Signal message should contain chart emoji."""
        from src.trading.models import EntrySignal
        signal = EntrySignal(
            signal_type="long_liquidation",
            liquidation_usd=50000.0,
            timestamp=datetime(2024, 1, 15, 10, 30, 0),
            dominant_side="long_liquidated",
            long_usd=40000.0,
            short_usd=10000.0
        )
        result = MessageFormatter.format_signal(True, signal)
        assert "📊" in result
    
    def test_contains_signal_type(self):
        """Signal message should contain signal type."""
        from src.trading.models import EntrySignal
        signal = EntrySignal(
            signal_type="long_liquidation",
            liquidation_usd=50000.0,
            timestamp=datetime(2024, 1, 15, 10, 30, 0),
            dominant_side="long_liquidated",
            long_usd=40000.0,
            short_usd=10000.0
        )
        result = MessageFormatter.format_signal(True, signal)
        assert "long\\_liquidation" in result
    
    def test_contains_liquidation_amount(self):
        """Signal message should contain liquidation USD amount."""
        from src.trading.models import EntrySignal
        signal = EntrySignal(
            signal_type="long_liquidation",
            liquidation_usd=50000.0,
            timestamp=datetime(2024, 1, 15, 10, 30, 0),
            dominant_side="long_liquidated",
            long_usd=40000.0,
            short_usd=10000.0
        )
        result = MessageFormatter.format_signal(True, signal)
        assert "$50,000\\.00" in result


class TestFormatSignalBlocked:
    """Tests for format_signal_blocked() method."""
    
    def test_contains_warning_emoji(self):
        """Blocked signal message should contain warning emoji."""
        from src.trading.models import EntrySignal
        signal = EntrySignal(
            signal_type="long_liquidation",
            liquidation_usd=50000.0,
            timestamp=datetime(2024, 1, 15, 10, 30, 0),
            dominant_side="long_liquidated",
            long_usd=40000.0,
            short_usd=10000.0
        )
        result = MessageFormatter.format_signal_blocked(True, signal, "Daily loss limit reached")
        assert "⚠️" in result
    
    def test_contains_reason(self):
        """Blocked signal message should contain the reason."""
        from src.trading.models import EntrySignal
        signal = EntrySignal(
            signal_type="long_liquidation",
            liquidation_usd=50000.0,
            timestamp=datetime(2024, 1, 15, 10, 30, 0),
            dominant_side="long_liquidated",
            long_usd=40000.0,
            short_usd=10000.0
        )
        result = MessageFormatter.format_signal_blocked(True, signal, "Daily loss limit reached")
        assert "Daily loss limit reached" in result


class TestFormatTradeEntry:
    """Tests for format_trade_entry() method."""
    
    def test_contains_mode_indicator(self):
        """Trade entry message should start with mode indicator."""
        result = MessageFormatter.format_trade_entry(True, "abc-123", "UP", 0.5500, 100.0)
        assert result.startswith(r"*\[DRY RUN\]*")
    
    def test_contains_trade_emoji(self):
        """Trade entry message should contain money emoji."""
        result = MessageFormatter.format_trade_entry(True, "abc-123", "UP", 0.5500, 100.0)
        assert "💰" in result
    
    def test_contains_trade_id(self):
        """Trade entry message should contain trade ID."""
        result = MessageFormatter.format_trade_entry(True, "abc-123", "UP", 0.5500, 100.0)
        assert "abc\\-123" in result
    
    def test_contains_direction(self):
        """Trade entry message should contain direction."""
        result = MessageFormatter.format_trade_entry(True, "abc-123", "UP", 0.5500, 100.0)
        assert "UP" in result
    
    def test_contains_price(self):
        """Trade entry message should contain entry price."""
        result = MessageFormatter.format_trade_entry(True, "abc-123", "UP", 0.5500, 100.0)
        assert "0\\.5500" in result
    
    def test_contains_size(self):
        """Trade entry message should contain bet size."""
        result = MessageFormatter.format_trade_entry(True, "abc-123", "UP", 0.5500, 100.0)
        assert "$100\\.00" in result

    def test_contains_bet_statistics_when_provided(self):
        """Trade entry message should contain dry-run bet statistics."""
        result = MessageFormatter.format_trade_entry(
            True,
            "abc-123",
            "UP",
            0.4500,
            10.0,
            reference_entry_price=50123.45,
            shares_bought=22.2222,
            max_profit=12.2222,
            max_loss=10.0,
        )
        assert "Reference BTC Entry" in result
        assert "50,123\\.45" in result
        assert "22\\.2222" in result
        assert "$12\\.22" in result
        assert "$10\\.00" in result


class TestFormatHedgeOpened:
    """Tests for format_hedge_opened() method."""
    
    def test_contains_mode_indicator(self):
        """Hedge opened message should start with mode indicator."""
        result = MessageFormatter.format_hedge_opened(True, "abc-123", "LONG", 45000.50, 3)
        assert result.startswith(r"*\[DRY RUN\]*")
    
    def test_contains_trade_emoji(self):
        """Hedge opened message should contain money emoji."""
        result = MessageFormatter.format_hedge_opened(True, "abc-123", "LONG", 45000.50, 3)
        assert "💰" in result
    
    def test_contains_side(self):
        """Hedge opened message should contain side."""
        result = MessageFormatter.format_hedge_opened(True, "abc-123", "LONG", 45000.50, 3)
        assert "LONG" in result
    
    def test_contains_leverage(self):
        """Hedge opened message should contain leverage."""
        result = MessageFormatter.format_hedge_opened(True, "abc-123", "LONG", 45000.50, 3)
        assert "3x" in result


class TestFormatTradeClosed:
    """Tests for format_trade_closed() method."""
    
    def test_contains_mode_indicator(self):
        """Trade closed message should start with mode indicator."""
        result = MessageFormatter.format_trade_closed(True, "abc-123", 50.0, -20.0, 30.0, 100.0)
        assert result.startswith(r"*\[DRY RUN\]*")
    
    def test_contains_trade_emoji(self):
        """Trade closed message should contain money emoji."""
        result = MessageFormatter.format_trade_closed(True, "abc-123", 50.0, -20.0, 30.0, 100.0)
        assert "💰" in result
    
    def test_contains_pnl_breakdown(self):
        """Trade closed message should contain PnL breakdown."""
        result = MessageFormatter.format_trade_closed(True, "abc-123", 50.0, -20.0, 30.0, 100.0)
        assert "$50\\.00" in result  # polymarket pnl
        assert "\\-$20\\.00" in result  # binance pnl
        assert "$30\\.00" in result  # total pnl
    
    def test_contains_daily_pnl(self):
        """Trade closed message should contain daily PnL."""
        result = MessageFormatter.format_trade_closed(True, "abc-123", 50.0, -20.0, 30.0, 100.0)
        assert "$100\\.00" in result  # daily pnl

    def test_contains_reference_prices_when_provided(self):
        """Trade closed message should contain explicitly labeled BTC reference prices when available."""
        result = MessageFormatter.format_trade_closed(
            True,
            "abc-123",
            50.0,
            -20.0,
            30.0,
            100.0,
            reference_entry_price=50000.0,
            reference_exit_price=49750.5,
        )
        assert "Reference BTC Entry" in result
        assert "Reference BTC Exit" in result
        assert "50,000\\.00" in result
        assert "49,750\\.50" in result
    
    def test_positive_pnl_green_emoji(self):
        """Positive PnL should show green emoji."""
        result = MessageFormatter.format_trade_closed(True, "abc-123", 50.0, -20.0, 30.0, 100.0)
        assert "🟢" in result
        assert "Result" in result
        assert "WIN" in result
    
    def test_negative_pnl_red_emoji(self):
        """Negative PnL should show red emoji."""
        result = MessageFormatter.format_trade_closed(True, "abc-123", -50.0, -20.0, -70.0, -100.0)
        assert "🔴" in result
        assert "Result" in result
        assert "LOSE" in result
    
    def test_handles_none_pnl_values(self):
        """Should handle None PnL values gracefully."""
        result = MessageFormatter.format_trade_closed(True, "abc-123", None, None, 0.0, 0.0)
        assert "N/A" in result


class TestFormatError:
    """Tests for format_error() method."""
    
    def test_contains_mode_indicator(self):
        """Error message should start with mode indicator."""
        ts = datetime(2024, 1, 15, 10, 30, 0)
        result = MessageFormatter.format_error(True, "API Error", "binance", "Connection timeout", ts)
        assert result.startswith(r"*\[DRY RUN\]*")
    
    def test_contains_error_emoji(self):
        """Error message should contain red emoji."""
        ts = datetime(2024, 1, 15, 10, 30, 0)
        result = MessageFormatter.format_error(True, "API Error", "binance", "Connection timeout", ts)
        assert "🔴" in result
    
    def test_contains_error_type(self):
        """Error message should contain error type."""
        ts = datetime(2024, 1, 15, 10, 30, 0)
        result = MessageFormatter.format_error(True, "API Error", "binance", "Connection timeout", ts)
        assert "API Error" in result
    
    def test_contains_exchange(self):
        """Error message should contain exchange name."""
        ts = datetime(2024, 1, 15, 10, 30, 0)
        result = MessageFormatter.format_error(True, "API Error", "binance", "Connection timeout", ts)
        assert "binance" in result
    
    def test_contains_message(self):
        """Error message should contain error message."""
        ts = datetime(2024, 1, 15, 10, 30, 0)
        result = MessageFormatter.format_error(True, "API Error", "binance", "Connection timeout", ts)
        assert "Connection timeout" in result


class TestFormatRiskAlert:
    """Tests for format_risk_alert() method."""
    
    def test_contains_mode_indicator(self):
        """Risk alert message should start with mode indicator."""
        result = MessageFormatter.format_risk_alert(True, "Daily Loss Limit", "Limit of $200 reached")
        assert result.startswith(r"*\[DRY RUN\]*")
    
    def test_warning_emoji_for_non_critical(self):
        """Non-critical alert should contain warning emoji."""
        result = MessageFormatter.format_risk_alert(True, "Daily Loss Limit", "Limit of $200 reached", is_critical=False)
        assert "⚠️" in result
    
    def test_critical_emoji_for_critical(self):
        """Critical alert should contain siren emoji."""
        result = MessageFormatter.format_risk_alert(True, "Position Close Failed", "Manual intervention required", is_critical=True)
        assert "🚨" in result
    
    def test_contains_alert_type(self):
        """Risk alert message should contain alert type."""
        result = MessageFormatter.format_risk_alert(True, "Daily Loss Limit", "Limit of $200 reached")
        assert "Daily Loss Limit" in result
    
    def test_contains_details(self):
        """Risk alert message should contain details."""
        result = MessageFormatter.format_risk_alert(True, "Daily Loss Limit", "Limit of $200 reached")
        assert "Limit of $200 reached" in result
    
    def test_critical_label_for_critical(self):
        """Critical alert should show CRITICAL ALERT label."""
        result = MessageFormatter.format_risk_alert(True, "Position Close Failed", "Manual intervention required", is_critical=True)
        assert "CRITICAL ALERT" in result
    
    def test_risk_alert_label_for_non_critical(self):
        """Non-critical alert should show Risk Alert label."""
        result = MessageFormatter.format_risk_alert(True, "Daily Loss Limit", "Limit of $200 reached", is_critical=False)
        assert "Risk Alert" in result


class TestFormatPnlSummary:
    """Tests for format_pnl_summary() method."""
    
    def test_contains_chart_emoji(self):
        """PnL summary should contain chart emoji."""
        from datetime import date
        result = MessageFormatter.format_pnl_summary(
            start_date=date(2024, 1, 15),
            end_date=date(2024, 1, 15),
            total_pnl=150.50,
            trade_count=5,
            win_count=3,
            loss_count=2,
            win_rate=0.6,
        )
        assert "📊" in result
    
    def test_single_date_format(self):
        """Single date should show just that date."""
        from datetime import date
        result = MessageFormatter.format_pnl_summary(
            start_date=date(2024, 1, 15),
            end_date=date(2024, 1, 15),
            total_pnl=150.50,
            trade_count=5,
            win_count=3,
            loss_count=2,
            win_rate=0.6,
        )
        assert "2024\\-01\\-15" in result
        assert "to" not in result
    
    def test_date_range_format(self):
        """Date range should show start to end."""
        from datetime import date
        result = MessageFormatter.format_pnl_summary(
            start_date=date(2024, 1, 15),
            end_date=date(2024, 1, 20),
            total_pnl=150.50,
            trade_count=5,
            win_count=3,
            loss_count=2,
            win_rate=0.6,
        )
        assert "2024\\-01\\-15 to 2024\\-01\\-20" in result
    
    def test_contains_total_pnl(self):
        """PnL summary should contain total PnL."""
        from datetime import date
        result = MessageFormatter.format_pnl_summary(
            start_date=date(2024, 1, 15),
            end_date=date(2024, 1, 15),
            total_pnl=1500.50,
            trade_count=5,
            win_count=3,
            loss_count=2,
            win_rate=0.6,
        )
        assert "$1,500\\.50" in result
    
    def test_contains_trade_count(self):
        """PnL summary should contain trade count."""
        from datetime import date
        result = MessageFormatter.format_pnl_summary(
            start_date=date(2024, 1, 15),
            end_date=date(2024, 1, 15),
            total_pnl=150.50,
            trade_count=5,
            win_count=3,
            loss_count=2,
            win_rate=0.6,
        )
        assert "Trades: 5" in result
    
    def test_contains_win_loss_count(self):
        """PnL summary should contain win and loss counts."""
        from datetime import date
        result = MessageFormatter.format_pnl_summary(
            start_date=date(2024, 1, 15),
            end_date=date(2024, 1, 15),
            total_pnl=150.50,
            trade_count=5,
            win_count=3,
            loss_count=2,
            win_rate=0.6,
        )
        assert "Wins: 3" in result
        assert "Losses: 2" in result
    
    def test_contains_win_rate(self):
        """PnL summary should contain win rate percentage."""
        from datetime import date
        result = MessageFormatter.format_pnl_summary(
            start_date=date(2024, 1, 15),
            end_date=date(2024, 1, 15),
            total_pnl=150.50,
            trade_count=5,
            win_count=3,
            loss_count=2,
            win_rate=0.6,
        )
        assert "60\\.0%" in result
    
    def test_positive_pnl_green_emoji(self):
        """Positive PnL should show green emoji."""
        from datetime import date
        result = MessageFormatter.format_pnl_summary(
            start_date=date(2024, 1, 15),
            end_date=date(2024, 1, 15),
            total_pnl=150.50,
            trade_count=5,
            win_count=3,
            loss_count=2,
            win_rate=0.6,
        )
        assert "🟢" in result
    
    def test_negative_pnl_red_emoji(self):
        """Negative PnL should show red emoji."""
        from datetime import date
        result = MessageFormatter.format_pnl_summary(
            start_date=date(2024, 1, 15),
            end_date=date(2024, 1, 15),
            total_pnl=-150.50,
            trade_count=5,
            win_count=2,
            loss_count=3,
            win_rate=0.4,
        )
        assert "🔴" in result


class TestFormatStatus:
    """Tests for format_status() method."""
    
    def test_contains_mode_indicator_dry_run(self):
        """Status message should start with [DRY RUN] mode indicator."""
        from datetime import timedelta
        result = MessageFormatter.format_status(
            dry_run=True,
            running=True,
            open_position=None,
            daily_pnl=50.0,
            daily_limit_remaining=150.0,
            uptime=timedelta(hours=2, minutes=30, seconds=15),
        )
        assert result.startswith(r"*\[DRY RUN\]*")
    
    def test_contains_mode_indicator_live(self):
        """Status message should start with [LIVE] mode indicator."""
        from datetime import timedelta
        result = MessageFormatter.format_status(
            dry_run=False,
            running=True,
            open_position=None,
            daily_pnl=50.0,
            daily_limit_remaining=150.0,
            uptime=timedelta(hours=2, minutes=30, seconds=15),
        )
        assert result.startswith(r"*\[LIVE\]*")
    
    def test_contains_chart_emoji(self):
        """Status message should contain chart emoji."""
        from datetime import timedelta
        result = MessageFormatter.format_status(
            dry_run=True,
            running=True,
            open_position=None,
            daily_pnl=50.0,
            daily_limit_remaining=150.0,
            uptime=timedelta(hours=2, minutes=30, seconds=15),
        )
        assert "📊" in result
    
    def test_running_state_shows_green_emoji(self):
        """Running state should show green emoji."""
        from datetime import timedelta
        result = MessageFormatter.format_status(
            dry_run=True,
            running=True,
            open_position=None,
            daily_pnl=50.0,
            daily_limit_remaining=150.0,
            uptime=timedelta(hours=2, minutes=30, seconds=15),
        )
        assert "🟢" in result
        assert "Running" in result
    
    def test_stopped_state_shows_red_emoji(self):
        """Stopped state should show red emoji."""
        from datetime import timedelta
        result = MessageFormatter.format_status(
            dry_run=True,
            running=False,
            open_position=None,
            daily_pnl=50.0,
            daily_limit_remaining=150.0,
            uptime=timedelta(hours=2, minutes=30, seconds=15),
        )
        assert "🔴" in result
        assert "Stopped" in result
    
    def test_no_open_position_shows_none(self):
        """No open position should show 'None'."""
        from datetime import timedelta
        result = MessageFormatter.format_status(
            dry_run=True,
            running=True,
            open_position=None,
            daily_pnl=50.0,
            daily_limit_remaining=150.0,
            uptime=timedelta(hours=2, minutes=30, seconds=15),
        )
        assert "Open Position" in result
        assert "None" in result
    
    def test_open_position_shows_details(self):
        """Open position should show direction and entry time."""
        from datetime import timedelta, timezone
        from src.trading.models import TradePair, PolymarketOrder, BinancePosition
        
        polymarket_order = PolymarketOrder(
            order_id="order123",
            market_id="market456",
            outcome="UP",
            side="BUY",
            size=10.0,
            price=0.5,
            status="filled",
            fill_price=0.5,
            fill_time=datetime(2024, 1, 15, 11, 0, 0, tzinfo=timezone.utc),
        )
        binance_position = BinancePosition(
            position_id="pos789",
            symbol="BTCUSDT",
            side="SHORT",
            size=0.001,
            leverage=3,
            entry_price=45000.0,
            margin_mode="isolated",
            status="open",
            pnl=None,
        )
        open_position = TradePair(
            trade_id="trade123",
            polymarket_order=polymarket_order,
            binance_position=binance_position,
            direction="UP",
            entry_time=datetime(2024, 1, 15, 11, 0, 0, tzinfo=timezone.utc),
            expiry_time=datetime(2024, 1, 15, 11, 5, 0, tzinfo=timezone.utc),
            status="open",
            polymarket_pnl=None,
            binance_pnl=None,
            total_pnl=None,
        )
        
        result = MessageFormatter.format_status(
            dry_run=True,
            running=True,
            open_position=open_position,
            daily_pnl=50.0,
            daily_limit_remaining=150.0,
            uptime=timedelta(hours=2, minutes=30, seconds=15),
        )
        assert "Direction" in result
        assert "UP" in result
        assert "Entry Time" in result
    
    def test_contains_daily_pnl(self):
        """Status message should contain daily PnL."""
        from datetime import timedelta
        result = MessageFormatter.format_status(
            dry_run=True,
            running=True,
            open_position=None,
            daily_pnl=150.50,
            daily_limit_remaining=49.50,
            uptime=timedelta(hours=2, minutes=30, seconds=15),
        )
        assert "Daily PnL" in result
        assert "$150\\.50" in result
    
    def test_contains_loss_limit_remaining(self):
        """Status message should contain loss limit remaining."""
        from datetime import timedelta
        result = MessageFormatter.format_status(
            dry_run=True,
            running=True,
            open_position=None,
            daily_pnl=50.0,
            daily_limit_remaining=150.0,
            uptime=timedelta(hours=2, minutes=30, seconds=15),
        )
        assert "Loss Limit Remaining" in result
        assert "$150\\.00" in result
    
    def test_contains_uptime(self):
        """Status message should contain uptime duration."""
        from datetime import timedelta
        result = MessageFormatter.format_status(
            dry_run=True,
            running=True,
            open_position=None,
            daily_pnl=50.0,
            daily_limit_remaining=150.0,
            uptime=timedelta(hours=2, minutes=30, seconds=15),
        )
        assert "Uptime" in result
        assert "2h 30m 15s" in result
    
    def test_uptime_zero(self):
        """Zero uptime should show 0h 0m 0s."""
        from datetime import timedelta
        result = MessageFormatter.format_status(
            dry_run=True,
            running=True,
            open_position=None,
            daily_pnl=50.0,
            daily_limit_remaining=150.0,
            uptime=timedelta(seconds=0),
        )
        assert "0h 0m 0s" in result
    
    def test_negative_daily_pnl(self):
        """Negative daily PnL should be formatted correctly."""
        from datetime import timedelta
        result = MessageFormatter.format_status(
            dry_run=True,
            running=True,
            open_position=None,
            daily_pnl=-75.25,
            daily_limit_remaining=24.75,
            uptime=timedelta(hours=1),
        )
        assert "\\-$75\\.25" in result


class TestFormatBalance:
    """Tests for format_balance() method."""
    
    def test_contains_mode_indicator_dry_run(self):
        """Balance message should start with [DRY RUN] mode indicator."""
        result = MessageFormatter.format_balance(
            dry_run=True,
            polymarket_balance=10000.0,
            binance_balance=10000.0,
            polymarket_error=None,
            binance_error=None,
        )
        assert result.startswith(r"*\[DRY RUN\]*")
    
    def test_contains_mode_indicator_live(self):
        """Balance message should start with [LIVE] mode indicator."""
        result = MessageFormatter.format_balance(
            dry_run=False,
            polymarket_balance=5000.0,
            binance_balance=3000.0,
            polymarket_error=None,
            binance_error=None,
        )
        assert result.startswith(r"*\[LIVE\]*")
    
    def test_contains_money_emoji(self):
        """Balance message should contain money bag emoji."""
        result = MessageFormatter.format_balance(
            dry_run=True,
            polymarket_balance=10000.0,
            binance_balance=10000.0,
            polymarket_error=None,
            binance_error=None,
        )
        assert "💰" in result
    
    def test_contains_account_balances_header(self):
        """Balance message should contain Account Balances header."""
        result = MessageFormatter.format_balance(
            dry_run=True,
            polymarket_balance=10000.0,
            binance_balance=10000.0,
            polymarket_error=None,
            binance_error=None,
        )
        assert "Account Balances" in result
    
    def test_contains_polymarket_label(self):
        """Balance message should contain Polymarket USDC label."""
        result = MessageFormatter.format_balance(
            dry_run=True,
            polymarket_balance=10000.0,
            binance_balance=10000.0,
            polymarket_error=None,
            binance_error=None,
        )
        assert "Polymarket USDC" in result
    
    def test_contains_binance_label(self):
        """Balance message should contain Binance Margin label."""
        result = MessageFormatter.format_balance(
            dry_run=True,
            polymarket_balance=10000.0,
            binance_balance=10000.0,
            polymarket_error=None,
            binance_error=None,
        )
        assert "Binance Margin" in result
    
    def test_contains_total_label(self):
        """Balance message should contain Total label."""
        result = MessageFormatter.format_balance(
            dry_run=True,
            polymarket_balance=10000.0,
            binance_balance=10000.0,
            polymarket_error=None,
            binance_error=None,
        )
        assert "Total" in result
    
    def test_formats_polymarket_balance(self):
        """Polymarket balance should be formatted correctly."""
        result = MessageFormatter.format_balance(
            dry_run=True,
            polymarket_balance=5000.50,
            binance_balance=3000.0,
            polymarket_error=None,
            binance_error=None,
        )
        assert "$5,000\\.50" in result
    
    def test_formats_binance_balance(self):
        """Binance balance should be formatted correctly."""
        result = MessageFormatter.format_balance(
            dry_run=True,
            polymarket_balance=5000.0,
            binance_balance=3500.75,
            polymarket_error=None,
            binance_error=None,
        )
        assert "$3,500\\.75" in result
    
    def test_calculates_total_balance(self):
        """Total should be sum of both balances."""
        result = MessageFormatter.format_balance(
            dry_run=True,
            polymarket_balance=5000.0,
            binance_balance=3000.0,
            polymarket_error=None,
            binance_error=None,
        )
        assert "$8,000\\.00" in result
    
    def test_polymarket_error_shows_error_message(self):
        """Polymarket error should show error indicator and message."""
        result = MessageFormatter.format_balance(
            dry_run=False,
            polymarket_balance=None,
            binance_balance=3000.0,
            polymarket_error="API timeout",
            binance_error=None,
        )
        assert "❌" in result
        assert "Error" in result
        assert "API timeout" in result
    
    def test_binance_error_shows_error_message(self):
        """Binance error should show error indicator and message."""
        result = MessageFormatter.format_balance(
            dry_run=False,
            polymarket_balance=5000.0,
            binance_balance=None,
            polymarket_error=None,
            binance_error="Connection refused",
        )
        assert "❌" in result
        assert "Error" in result
        assert "Connection refused" in result
    
    def test_partial_failure_shows_successful_balance(self):
        """Partial failure should still show successful balance."""
        result = MessageFormatter.format_balance(
            dry_run=False,
            polymarket_balance=5000.0,
            binance_balance=None,
            polymarket_error=None,
            binance_error="Connection refused",
        )
        assert "$5,000\\.00" in result
    
    def test_partial_failure_total_shows_na(self):
        """Partial failure should show N/A for total."""
        result = MessageFormatter.format_balance(
            dry_run=False,
            polymarket_balance=5000.0,
            binance_balance=None,
            polymarket_error=None,
            binance_error="Connection refused",
        )
        assert "N/A" in result
        assert "partial data" in result
    
    def test_both_errors_shows_both_error_messages(self):
        """Both errors should show both error messages."""
        result = MessageFormatter.format_balance(
            dry_run=False,
            polymarket_balance=None,
            binance_balance=None,
            polymarket_error="Polymarket API error",
            binance_error="Binance API error",
        )
        assert "Polymarket API error" in result
        assert "Binance API error" in result
    
    def test_both_errors_total_shows_na(self):
        """Both errors should show N/A for total."""
        result = MessageFormatter.format_balance(
            dry_run=False,
            polymarket_balance=None,
            binance_balance=None,
            polymarket_error="Polymarket API error",
            binance_error="Binance API error",
        )
        assert "N/A" in result
    
    def test_large_balances_formatted_with_commas(self):
        """Large balances should have thousand separators."""
        result = MessageFormatter.format_balance(
            dry_run=True,
            polymarket_balance=1000000.0,
            binance_balance=500000.0,
            polymarket_error=None,
            binance_error=None,
        )
        assert "$1,000,000\\.00" in result
        assert "$500,000\\.00" in result
        assert "$1,500,000\\.00" in result
    
    def test_zero_balances(self):
        """Zero balances should be formatted correctly."""
        result = MessageFormatter.format_balance(
            dry_run=True,
            polymarket_balance=0.0,
            binance_balance=0.0,
            polymarket_error=None,
            binance_error=None,
        )
        assert "$0\\.00" in result
    
    def test_escapes_special_characters_in_error(self):
        """Special characters in error messages should be escaped."""
        result = MessageFormatter.format_balance(
            dry_run=False,
            polymarket_balance=None,
            binance_balance=3000.0,
            polymarket_error="Error: [timeout] (500)",
            binance_error=None,
        )
        # Special characters should be escaped
        assert r"\[timeout\]" in result
        assert r"\(500\)" in result
