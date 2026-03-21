"""Unit tests for TelegramCommandHandler class."""

import pytest
from datetime import date, datetime, timezone
from unittest.mock import MagicMock

from src.trading.telegram_command_handler import TelegramCommandHandler
from src.trading.pnl_aggregator import PnLAggregator, PnLSummary
from src.trading.models import TradePair, PolymarketOrder, BinancePosition


class TestHandlePnlCommand:
    """Tests for _handle_pnl_command() method."""
    
    @pytest.fixture
    def mock_dependencies(self):
        """Create mock dependencies for TelegramCommandHandler."""
        notifier = MagicMock()
        pnl_aggregator = MagicMock(spec=PnLAggregator)
        risk_controller = MagicMock()
        position_manager = MagicMock()
        binance_trader = MagicMock()
        polymarket_connector = MagicMock()
        
        return {
            "token": "test_token",
            "chat_id": "123456",
            "notifier": notifier,
            "pnl_aggregator": pnl_aggregator,
            "risk_controller": risk_controller,
            "position_manager": position_manager,
            "binance_trader": binance_trader,
            "polymarket_connector": polymarket_connector,
            "dry_run": True,
            "start_time": datetime(2024, 1, 15, 10, 0, 0),
        }
    
    @pytest.fixture
    def handler(self, mock_dependencies):
        """Create a TelegramCommandHandler instance."""
        return TelegramCommandHandler(**mock_dependencies)
    
    @pytest.mark.asyncio
    async def test_no_args_uses_today(self, handler):
        """No arguments should query today's PnL."""
        today = date.today()
        handler.pnl_aggregator.get_pnl_for_date.return_value = PnLSummary(
            start_date=today,
            end_date=today,
            total_pnl=150.50,
            trade_count=5,
            win_count=3,
            loss_count=2,
            win_rate=0.6,
        )
        
        result = await handler._handle_pnl_command([])
        
        handler.pnl_aggregator.get_pnl_for_date.assert_called_once_with(today)
        assert "📊" in result
        assert "$150\\.50" in result
    
    @pytest.mark.asyncio
    async def test_single_date_arg(self, handler):
        """Single date argument should query that specific date."""
        target_date = date(2024, 1, 15)
        handler.pnl_aggregator.get_pnl_for_date.return_value = PnLSummary(
            start_date=target_date,
            end_date=target_date,
            total_pnl=200.00,
            trade_count=3,
            win_count=2,
            loss_count=1,
            win_rate=0.667,
        )
        
        result = await handler._handle_pnl_command(["2024-01-15"])
        
        handler.pnl_aggregator.get_pnl_for_date.assert_called_once_with(target_date)
        assert "📊" in result
        assert "$200\\.00" in result
    
    @pytest.mark.asyncio
    async def test_date_range_args(self, handler):
        """Two date arguments should query the date range."""
        start_date = date(2024, 1, 10)
        end_date = date(2024, 1, 15)
        handler.pnl_aggregator.get_pnl_for_range.return_value = PnLSummary(
            start_date=start_date,
            end_date=end_date,
            total_pnl=500.00,
            trade_count=10,
            win_count=6,
            loss_count=4,
            win_rate=0.6,
        )
        
        result = await handler._handle_pnl_command(["2024-01-10", "2024-01-15"])
        
        handler.pnl_aggregator.get_pnl_for_range.assert_called_once_with(start_date, end_date)
        assert "📊" in result
        assert "$500\\.00" in result
        assert "2024\\-01\\-10 to 2024\\-01\\-15" in result
    
    @pytest.mark.asyncio
    async def test_invalid_date_format(self, handler):
        """Invalid date format should return usage help."""
        result = await handler._handle_pnl_command(["invalid-date"])
        
        assert "Invalid date format" in result
        assert "YYYY\\-MM\\-DD" in result
    
    @pytest.mark.asyncio
    async def test_end_date_before_start_date(self, handler):
        """End date before start date should return error."""
        result = await handler._handle_pnl_command(["2024-01-15", "2024-01-10"])
        
        assert "End date must be after start date" in result
    
    @pytest.mark.asyncio
    async def test_too_many_arguments(self, handler):
        """More than two arguments should return usage help."""
        result = await handler._handle_pnl_command(["2024-01-10", "2024-01-15", "extra"])
        
        assert "Too many arguments" in result
    
    @pytest.mark.asyncio
    async def test_no_trades_found(self, handler):
        """No trades should return appropriate message."""
        today = date.today()
        handler.pnl_aggregator.get_pnl_for_date.return_value = PnLSummary(
            start_date=today,
            end_date=today,
            total_pnl=0.0,
            trade_count=0,
            win_count=0,
            loss_count=0,
            win_rate=0.0,
        )
        
        result = await handler._handle_pnl_command([])
        
        assert result == "No trades found for the specified period"
    
    @pytest.mark.asyncio
    async def test_response_contains_win_rate(self, handler):
        """Response should contain win rate percentage."""
        today = date.today()
        handler.pnl_aggregator.get_pnl_for_date.return_value = PnLSummary(
            start_date=today,
            end_date=today,
            total_pnl=150.50,
            trade_count=5,
            win_count=3,
            loss_count=2,
            win_rate=0.6,
        )
        
        result = await handler._handle_pnl_command([])
        
        assert "60\\.0%" in result
    
    @pytest.mark.asyncio
    async def test_response_contains_trade_count(self, handler):
        """Response should contain trade count."""
        today = date.today()
        handler.pnl_aggregator.get_pnl_for_date.return_value = PnLSummary(
            start_date=today,
            end_date=today,
            total_pnl=150.50,
            trade_count=5,
            win_count=3,
            loss_count=2,
            win_rate=0.6,
        )
        
        result = await handler._handle_pnl_command([])
        
        assert "Trades: 5" in result
    
    @pytest.mark.asyncio
    async def test_response_contains_win_loss_count(self, handler):
        """Response should contain win and loss counts."""
        today = date.today()
        handler.pnl_aggregator.get_pnl_for_date.return_value = PnLSummary(
            start_date=today,
            end_date=today,
            total_pnl=150.50,
            trade_count=5,
            win_count=3,
            loss_count=2,
            win_rate=0.6,
        )
        
        result = await handler._handle_pnl_command([])
        
        assert "Wins: 3" in result
        assert "Losses: 2" in result


class TestHandleStatusCommand:
    """Tests for _handle_status_command() method."""
    
    @pytest.fixture
    def mock_dependencies(self):
        """Create mock dependencies for TelegramCommandHandler."""
        notifier = MagicMock()
        pnl_aggregator = MagicMock(spec=PnLAggregator)
        risk_controller = MagicMock()
        risk_controller.get_daily_pnl.return_value = -25.50
        risk_controller._max_daily_loss = 100.0
        position_manager = MagicMock()
        position_manager.get_open_position.return_value = None
        binance_trader = MagicMock()
        polymarket_connector = MagicMock()
        
        return {
            "token": "test_token",
            "chat_id": "123456",
            "notifier": notifier,
            "pnl_aggregator": pnl_aggregator,
            "risk_controller": risk_controller,
            "position_manager": position_manager,
            "binance_trader": binance_trader,
            "polymarket_connector": polymarket_connector,
            "dry_run": True,
            "start_time": datetime(2024, 1, 15, 10, 0, 0),
        }
    
    @pytest.fixture
    def handler(self, mock_dependencies):
        """Create a TelegramCommandHandler instance."""
        handler = TelegramCommandHandler(**mock_dependencies)
        handler._running = True  # Simulate running state
        return handler
    
    @pytest.mark.asyncio
    async def test_status_contains_mode_indicator_dry_run(self, handler):
        """Status response should contain [DRY RUN] mode indicator."""
        result = await handler._handle_status_command()
        
        assert r"\[DRY RUN\]" in result
    
    @pytest.mark.asyncio
    async def test_status_contains_mode_indicator_live(self, mock_dependencies):
        """Status response should contain [LIVE] mode indicator when not dry run."""
        mock_dependencies["dry_run"] = False
        handler = TelegramCommandHandler(**mock_dependencies)
        handler._running = True
        
        result = await handler._handle_status_command()
        
        assert r"\[LIVE\]" in result
    
    @pytest.mark.asyncio
    async def test_status_contains_running_state(self, handler):
        """Status response should contain running state."""
        result = await handler._handle_status_command()
        
        assert "Running" in result
        assert "🟢" in result
    
    @pytest.mark.asyncio
    async def test_status_contains_stopped_state(self, mock_dependencies):
        """Status response should contain stopped state when not running."""
        handler = TelegramCommandHandler(**mock_dependencies)
        handler._running = False
        
        result = await handler._handle_status_command()
        
        assert "Stopped" in result
        assert "🔴" in result
    
    @pytest.mark.asyncio
    async def test_status_no_open_position(self, handler):
        """Status response should show 'None' when no open position."""
        result = await handler._handle_status_command()
        
        assert "Open Position" in result
        assert "None" in result
    
    @pytest.mark.asyncio
    async def test_status_with_open_position(self, mock_dependencies):
        """Status response should show position details when position is open."""
        # Create a mock open position
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
        
        mock_dependencies["position_manager"].get_open_position.return_value = open_position
        handler = TelegramCommandHandler(**mock_dependencies)
        handler._running = True
        
        result = await handler._handle_status_command()
        
        assert "Direction" in result
        assert "UP" in result
        assert "Entry Time" in result
    
    @pytest.mark.asyncio
    async def test_status_contains_daily_pnl(self, handler):
        """Status response should contain daily PnL."""
        result = await handler._handle_status_command()
        
        assert "Daily PnL" in result
        # -$25.50 should be formatted
        assert "$25\\.50" in result
    
    @pytest.mark.asyncio
    async def test_status_contains_loss_limit_remaining(self, handler):
        """Status response should contain daily loss limit remaining."""
        result = await handler._handle_status_command()
        
        assert "Loss Limit Remaining" in result
        # max_daily_loss (100) + daily_pnl (-25.50) = 74.50
        assert "$74\\.50" in result
    
    @pytest.mark.asyncio
    async def test_status_contains_uptime(self, handler):
        """Status response should contain uptime duration."""
        result = await handler._handle_status_command()
        
        assert "Uptime" in result
        # Should contain hours, minutes, seconds format
        assert "h" in result
        assert "m" in result
        assert "s" in result
    
    @pytest.mark.asyncio
    async def test_status_contains_bot_status_header(self, handler):
        """Status response should contain Bot Status header."""
        result = await handler._handle_status_command()
        
        assert "Bot Status" in result
        assert "📊" in result


class TestHandleBalanceCommand:
    """Tests for _handle_balance_command() method."""
    
    @pytest.fixture
    def mock_dependencies(self):
        """Create mock dependencies for TelegramCommandHandler."""
        notifier = MagicMock()
        pnl_aggregator = MagicMock(spec=PnLAggregator)
        risk_controller = MagicMock()
        position_manager = MagicMock()
        binance_trader = MagicMock()
        polymarket_connector = MagicMock()
        
        return {
            "token": "test_token",
            "chat_id": "123456",
            "notifier": notifier,
            "pnl_aggregator": pnl_aggregator,
            "risk_controller": risk_controller,
            "position_manager": position_manager,
            "binance_trader": binance_trader,
            "polymarket_connector": polymarket_connector,
            "dry_run": True,
            "start_time": datetime(2024, 1, 15, 10, 0, 0),
        }
    
    @pytest.fixture
    def handler(self, mock_dependencies):
        """Create a TelegramCommandHandler instance."""
        return TelegramCommandHandler(**mock_dependencies)
    
    @pytest.mark.asyncio
    async def test_balance_contains_mode_indicator_dry_run(self, handler):
        """Balance response should contain [DRY RUN] mode indicator."""
        result = await handler._handle_balance_command()
        
        assert r"\[DRY RUN\]" in result
    
    @pytest.mark.asyncio
    async def test_balance_contains_mode_indicator_live(self, mock_dependencies):
        """Balance response should contain [LIVE] mode indicator when not dry run."""
        mock_dependencies["dry_run"] = False
        # Set up mock return values for live mode
        mock_dependencies["polymarket_connector"].get_balance = MagicMock(return_value=5000.0)
        mock_dependencies["binance_trader"].get_available_margin = MagicMock(return_value=3000.0)
        handler = TelegramCommandHandler(**mock_dependencies)
        
        result = await handler._handle_balance_command()
        
        assert r"\[LIVE\]" in result
    
    @pytest.mark.asyncio
    async def test_dry_run_returns_simulated_balances(self, handler):
        """Dry run mode should return simulated balances ($10,000 each)."""
        result = await handler._handle_balance_command()
        
        # Should contain $10,000.00 for both exchanges
        assert "$10,000\\.00" in result
        # Total should be $20,000.00
        assert "$20,000\\.00" in result
    
    @pytest.mark.asyncio
    async def test_dry_run_does_not_call_exchange_apis(self, handler):
        """Dry run mode should not call exchange APIs."""
        await handler._handle_balance_command()
        
        # Verify exchange APIs were not called
        handler.polymarket_connector.get_balance.assert_not_called()
        handler.binance_trader.get_available_margin.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_live_mode_queries_actual_balances(self, mock_dependencies):
        """Live mode should query actual balances from exchanges."""
        mock_dependencies["dry_run"] = False
        
        # Create async mock functions
        async def mock_get_balance():
            return 5000.0
        
        async def mock_get_margin():
            return 3000.0
        
        mock_dependencies["polymarket_connector"].get_balance = mock_get_balance
        mock_dependencies["binance_trader"].get_available_margin = mock_get_margin
        handler = TelegramCommandHandler(**mock_dependencies)
        
        result = await handler._handle_balance_command()
        
        # Should contain actual balances
        assert "$5,000\\.00" in result
        assert "$3,000\\.00" in result
        # Total should be $8,000.00
        assert "$8,000\\.00" in result
    
    @pytest.mark.asyncio
    async def test_balance_contains_polymarket_label(self, handler):
        """Balance response should contain Polymarket USDC label."""
        result = await handler._handle_balance_command()
        
        assert "Polymarket USDC" in result
    
    @pytest.mark.asyncio
    async def test_balance_contains_binance_label(self, handler):
        """Balance response should contain Binance Margin label."""
        result = await handler._handle_balance_command()
        
        assert "Binance Margin" in result
    
    @pytest.mark.asyncio
    async def test_balance_contains_total(self, handler):
        """Balance response should contain total combined balance."""
        result = await handler._handle_balance_command()
        
        assert "Total" in result
    
    @pytest.mark.asyncio
    async def test_balance_contains_emoji(self, handler):
        """Balance response should contain money bag emoji."""
        result = await handler._handle_balance_command()
        
        assert "💰" in result
    
    @pytest.mark.asyncio
    async def test_balance_contains_header(self, handler):
        """Balance response should contain Account Balances header."""
        result = await handler._handle_balance_command()
        
        assert "Account Balances" in result
    
    @pytest.mark.asyncio
    async def test_partial_failure_polymarket_error(self, mock_dependencies):
        """Should handle Polymarket API failure gracefully."""
        mock_dependencies["dry_run"] = False
        
        # Polymarket fails, Binance succeeds
        async def mock_get_balance():
            raise Exception("Polymarket API timeout")
        
        async def mock_get_margin():
            return 3000.0
        
        mock_dependencies["polymarket_connector"].get_balance = mock_get_balance
        mock_dependencies["binance_trader"].get_available_margin = mock_get_margin
        handler = TelegramCommandHandler(**mock_dependencies)
        
        result = await handler._handle_balance_command()
        
        # Should show error for Polymarket
        assert "Error" in result
        assert "Polymarket API timeout" in result
        # Should show Binance balance
        assert "$3,000\\.00" in result
        # Total should be N/A
        assert "N/A" in result
    
    @pytest.mark.asyncio
    async def test_partial_failure_binance_error(self, mock_dependencies):
        """Should handle Binance API failure gracefully."""
        mock_dependencies["dry_run"] = False
        
        # Polymarket succeeds, Binance fails
        async def mock_get_balance():
            return 5000.0
        
        async def mock_get_margin():
            raise Exception("Binance connection refused")
        
        mock_dependencies["polymarket_connector"].get_balance = mock_get_balance
        mock_dependencies["binance_trader"].get_available_margin = mock_get_margin
        handler = TelegramCommandHandler(**mock_dependencies)
        
        result = await handler._handle_balance_command()
        
        # Should show Polymarket balance
        assert "$5,000\\.00" in result
        # Should show error for Binance
        assert "Error" in result
        assert "Binance connection refused" in result
        # Total should be N/A
        assert "N/A" in result
    
    @pytest.mark.asyncio
    async def test_both_exchanges_fail(self, mock_dependencies):
        """Should handle both exchanges failing gracefully."""
        mock_dependencies["dry_run"] = False
        
        # Both fail
        async def mock_get_balance():
            raise Exception("Polymarket error")
        
        async def mock_get_margin():
            raise Exception("Binance error")
        
        mock_dependencies["polymarket_connector"].get_balance = mock_get_balance
        mock_dependencies["binance_trader"].get_available_margin = mock_get_margin
        handler = TelegramCommandHandler(**mock_dependencies)
        
        result = await handler._handle_balance_command()
        
        # Should show errors for both
        assert "Polymarket error" in result
        assert "Binance error" in result
        # Total should be N/A
        assert "N/A" in result
