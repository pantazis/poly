"""Tests for RiskController component."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.trading.risk_controller import RiskController


class TestRiskControllerInit:
    """Tests for RiskController initialization."""
    
    def test_default_values(self):
        """Test default initialization values."""
        controller = RiskController()
        
        assert controller._max_daily_loss == 100.0
        assert controller._max_concurrent_positions == 1
        assert controller._polymarket_connector is None
        assert controller._binance_trader is None
        assert controller._daily_pnl == 0.0
    
    def test_custom_values(self):
        """Test initialization with custom values."""
        mock_pm = MagicMock()
        mock_bn = MagicMock()
        
        controller = RiskController(
            max_daily_loss=200.0,
            max_concurrent_positions=3,
            polymarket_connector=mock_pm,
            binance_trader=mock_bn,
        )
        
        assert controller._max_daily_loss == 200.0
        assert controller._max_concurrent_positions == 3
        assert controller._polymarket_connector is mock_pm
        assert controller._binance_trader is mock_bn


class TestRecordPnl:
    """Tests for record_pnl method."""
    
    def test_record_positive_pnl(self):
        """Test recording a profit."""
        controller = RiskController()
        
        controller.record_pnl(50.0)
        
        assert controller.get_daily_pnl() == 50.0
    
    def test_record_negative_pnl(self):
        """Test recording a loss."""
        controller = RiskController()
        
        controller.record_pnl(-30.0)
        
        assert controller.get_daily_pnl() == -30.0
    
    def test_record_multiple_pnl(self):
        """Test recording multiple PnL entries."""
        controller = RiskController()
        
        controller.record_pnl(20.0)
        controller.record_pnl(-50.0)
        controller.record_pnl(10.0)
        
        assert controller.get_daily_pnl() == -20.0


class TestGetDailyPnl:
    """Tests for get_daily_pnl method."""
    
    def test_initial_pnl_is_zero(self):
        """Test that initial daily PnL is zero."""
        controller = RiskController()
        
        assert controller.get_daily_pnl() == 0.0
    
    def test_returns_accumulated_pnl(self):
        """Test that get_daily_pnl returns accumulated value."""
        controller = RiskController()
        
        controller.record_pnl(100.0)
        controller.record_pnl(-25.0)
        
        assert controller.get_daily_pnl() == 75.0


class TestIsDailyLimitReached:
    """Tests for is_daily_limit_reached method."""
    
    def test_limit_not_reached_initially(self):
        """Test that limit is not reached with zero PnL."""
        controller = RiskController(max_daily_loss=100.0)
        
        assert controller.is_daily_limit_reached() is False
    
    def test_limit_not_reached_with_profit(self):
        """Test that limit is not reached with positive PnL."""
        controller = RiskController(max_daily_loss=100.0)
        controller.record_pnl(50.0)
        
        assert controller.is_daily_limit_reached() is False
    
    def test_limit_not_reached_with_small_loss(self):
        """Test that limit is not reached with loss below threshold."""
        controller = RiskController(max_daily_loss=100.0)
        controller.record_pnl(-50.0)
        
        assert controller.is_daily_limit_reached() is False
    
    def test_limit_reached_at_exact_threshold(self):
        """Test that limit is reached at exact threshold."""
        controller = RiskController(max_daily_loss=100.0)
        controller.record_pnl(-100.0)
        
        assert controller.is_daily_limit_reached() is True
    
    def test_limit_reached_beyond_threshold(self):
        """Test that limit is reached beyond threshold."""
        controller = RiskController(max_daily_loss=100.0)
        controller.record_pnl(-150.0)
        
        assert controller.is_daily_limit_reached() is True


class TestCanOpenPosition:
    """Tests for can_open_position async method."""
    
    @pytest.mark.asyncio
    async def test_blocked_by_daily_limit(self):
        """Test that position is blocked when daily limit reached."""
        controller = RiskController(max_daily_loss=100.0)
        controller.record_pnl(-100.0)
        
        allowed, reason = await controller.can_open_position(
            bet_size=10.0,
            hedge_margin_required=15.0,
            current_open_positions=0,
        )
        
        assert allowed is False
        assert "Daily loss limit reached" in reason
    
    @pytest.mark.asyncio
    async def test_blocked_by_max_positions(self):
        """Test that position is blocked when max positions reached."""
        controller = RiskController(max_concurrent_positions=1)
        
        allowed, reason = await controller.can_open_position(
            bet_size=10.0,
            hedge_margin_required=15.0,
            current_open_positions=1,
        )
        
        assert allowed is False
        assert "Max concurrent positions reached" in reason
    
    @pytest.mark.asyncio
    async def test_blocked_by_insufficient_polymarket_balance(self):
        """Test that position is blocked when Polymarket balance insufficient."""
        mock_pm = MagicMock()
        mock_pm.get_balance = AsyncMock(return_value=5.0)
        
        controller = RiskController(polymarket_connector=mock_pm)
        
        allowed, reason = await controller.can_open_position(
            bet_size=10.0,
            hedge_margin_required=15.0,
            current_open_positions=0,
        )
        
        assert allowed is False
        assert "Insufficient Polymarket balance" in reason
    
    @pytest.mark.asyncio
    async def test_blocked_by_insufficient_binance_margin(self):
        """Test that position is blocked when Binance margin insufficient."""
        mock_pm = MagicMock()
        mock_pm.get_balance = AsyncMock(return_value=100.0)
        
        mock_bn = MagicMock()
        mock_bn.get_available_margin = AsyncMock(return_value=10.0)
        
        controller = RiskController(
            polymarket_connector=mock_pm,
            binance_trader=mock_bn,
        )
        
        allowed, reason = await controller.can_open_position(
            bet_size=10.0,
            hedge_margin_required=15.0,
            current_open_positions=0,
        )
        
        assert allowed is False
        assert "Insufficient Binance margin" in reason
    
    @pytest.mark.asyncio
    async def test_allowed_when_all_checks_pass(self):
        """Test that position is allowed when all checks pass."""
        mock_pm = MagicMock()
        mock_pm.get_balance = AsyncMock(return_value=100.0)
        
        mock_bn = MagicMock()
        mock_bn.get_available_margin = AsyncMock(return_value=50.0)
        
        controller = RiskController(
            max_daily_loss=100.0,
            max_concurrent_positions=1,
            polymarket_connector=mock_pm,
            binance_trader=mock_bn,
        )
        
        allowed, reason = await controller.can_open_position(
            bet_size=10.0,
            hedge_margin_required=15.0,
            current_open_positions=0,
        )
        
        assert allowed is True
        assert reason == ""
    
    @pytest.mark.asyncio
    async def test_allowed_without_connectors(self):
        """Test that position is allowed when no connectors configured."""
        controller = RiskController()
        
        allowed, reason = await controller.can_open_position(
            bet_size=10.0,
            hedge_margin_required=15.0,
            current_open_positions=0,
        )
        
        assert allowed is True
        assert reason == ""


class TestResetDailyPnl:
    """Tests for reset_daily_pnl method."""
    
    def test_reset_clears_pnl(self):
        """Test that reset clears accumulated PnL."""
        controller = RiskController()
        controller.record_pnl(-50.0)
        controller.record_pnl(20.0)
        
        assert controller.get_daily_pnl() == -30.0
        
        controller.reset_daily_pnl()
        
        assert controller.get_daily_pnl() == 0.0
    
    def test_reset_clears_limit_reached_state(self):
        """Test that reset clears the daily limit reached state."""
        controller = RiskController(max_daily_loss=100.0)
        controller.record_pnl(-100.0)
        
        assert controller.is_daily_limit_reached() is True
        
        controller.reset_daily_pnl()
        
        assert controller.is_daily_limit_reached() is False
