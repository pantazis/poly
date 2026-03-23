"""Tests for the TradingBot orchestrator."""

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.trading.bot import TradingBot
from src.trading.config import TradingConfig
from src.trading.models import BinancePosition, EntrySignal, PolymarketOrder, TradePair


@pytest.fixture
def mock_collector():
    """Create a mock LiquidationCollector."""
    collector = MagicMock()
    collector.get_aggregations.return_value = []
    return collector


@pytest.fixture
def trading_config(tmp_path):
    """Create a test trading configuration."""
    return TradingConfig(
        entry_threshold_min=25_000.0,
        entry_threshold_max=100_000.0,
        liquidation_window_minutes=5,
        bet_size=10.0,
        discount_percent=10.0,
        polymarket_private_key="0" * 64,
        hedge_leverage=3,
        hedge_size=15.0,
        binance_api_key="test_key",
        binance_api_secret="test_secret",
        max_daily_loss=100.0,
        max_concurrent_positions=1,
        dry_run=True,
        log_dir=tmp_path / "logs",
    )


class TestTradingBotInit:
    """Tests for TradingBot initialization."""
    
    def test_init_creates_all_components(self, trading_config, mock_collector):
        """TradingBot should initialize all required components."""
        bot = TradingBot(config=trading_config, collector=mock_collector)
        
        assert bot._config == trading_config
        assert bot._collector == mock_collector
        assert bot._trade_logger is not None
        assert bot._polymarket_connector is not None
        assert bot._binance_trader is not None
        assert bot._position_manager is not None
        assert bot._risk_controller is not None
        assert bot._signal_detector is not None
    
    def test_init_sets_dry_run_mode(self, trading_config, mock_collector):
        """TradingBot should pass dry_run flag to connectors."""
        bot = TradingBot(config=trading_config, collector=mock_collector)
        
        assert bot._polymarket_connector._dry_run is True
        assert bot._polymarket_connector._use_live_market_data_in_dry_run is True
        assert bot._binance_trader.dry_run is True
    
    def test_init_configures_signal_detector_thresholds(self, trading_config, mock_collector):
        """TradingBot should configure SignalDetector with correct thresholds."""
        bot = TradingBot(config=trading_config, collector=mock_collector)
        
        assert bot._signal_detector._threshold_min == 25_000.0
        assert bot._signal_detector._threshold_max == 100_000.0
        assert bot._signal_detector._window_minutes == 5
    
    def test_init_configures_risk_controller(self, trading_config, mock_collector):
        """TradingBot should configure RiskController with correct limits."""
        bot = TradingBot(config=trading_config, collector=mock_collector)
        
        assert bot._risk_controller._max_daily_loss == 100.0
        assert bot._risk_controller._max_concurrent_positions == 1


class TestTradingBotHandleSignal:
    """Tests for signal handling."""
    
    @pytest.fixture
    def entry_signal(self):
        """Create a test entry signal."""
        return EntrySignal(
            signal_type="long_liquidation",
            liquidation_usd=50_000.0,
            timestamp=datetime.now(timezone.utc),
            dominant_side="long_liquidated",
            long_usd=35_000.0,
            short_usd=15_000.0,
        )
    
    @pytest.mark.asyncio
    async def test_handle_signal_checks_risk_controller(
        self, trading_config, mock_collector, entry_signal
    ):
        """_handle_signal should check risk controller before placing orders."""
        bot = TradingBot(config=trading_config, collector=mock_collector)
        
        # Mock risk controller to block the trade
        bot._risk_controller.can_open_position = AsyncMock(
            return_value=(False, "Daily loss limit reached")
        )
        bot._trade_logger.log_signal = AsyncMock()
        bot._polymarket_connector.place_order = AsyncMock()
        
        await bot._handle_signal(entry_signal)
        
        # Should check risk controller
        bot._risk_controller.can_open_position.assert_called_once()
        
        # Should NOT place order when blocked
        bot._polymarket_connector.place_order.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_handle_signal_logs_signal(
        self, trading_config, mock_collector, entry_signal
    ):
        """_handle_signal should log the signal via trade_logger."""
        bot = TradingBot(config=trading_config, collector=mock_collector)
        
        # Mock components
        bot._risk_controller.can_open_position = AsyncMock(return_value=(True, ""))
        bot._trade_logger.log_signal = AsyncMock()
        
        # Mock order placement to return cancelled order
        cancelled_order = PolymarketOrder(
            order_id="test-order",
            market_id="btc-5min-binary",
            outcome="DOWN",
            side="BUY",
            size=10.0,
            price=0.45,
            status="cancelled",
            fill_price=None,
            fill_time=None,
        )
        bot._polymarket_connector.place_order = AsyncMock(return_value=cancelled_order)
        
        await bot._handle_signal(entry_signal)
        
        # Should log the signal
        bot._trade_logger.log_signal.assert_called_once_with(
            entry_signal, is_dry_run=True
        )
    
    @pytest.mark.asyncio
    async def test_handle_signal_maps_long_liquidation_to_down(
        self, trading_config, mock_collector
    ):
        """Long liquidation signal should result in DOWN outcome on Polymarket."""
        bot = TradingBot(config=trading_config, collector=mock_collector)
        
        signal = EntrySignal(
            signal_type="long_liquidation",
            liquidation_usd=50_000.0,
            timestamp=datetime.now(timezone.utc),
            dominant_side="long_liquidated",
            long_usd=35_000.0,
            short_usd=15_000.0,
        )
        
        # Mock components
        bot._risk_controller.can_open_position = AsyncMock(return_value=(True, ""))
        bot._trade_logger.log_signal = AsyncMock()
        
        cancelled_order = PolymarketOrder(
            order_id="test-order",
            market_id="btc-5min-binary",
            outcome="DOWN",
            side="BUY",
            size=10.0,
            price=0.45,
            status="cancelled",
            fill_price=None,
            fill_time=None,
        )
        bot._polymarket_connector.place_order = AsyncMock(return_value=cancelled_order)
        
        await bot._handle_signal(signal)
        
        # Should place DOWN order
        bot._polymarket_connector.place_order.assert_called_once()
        call_args = bot._polymarket_connector.place_order.call_args
        assert call_args.kwargs["outcome"] == "DOWN"
    
    @pytest.mark.asyncio
    async def test_handle_signal_maps_short_liquidation_to_up(
        self, trading_config, mock_collector
    ):
        """Short liquidation signal should result in UP outcome on Polymarket."""
        bot = TradingBot(config=trading_config, collector=mock_collector)
        
        signal = EntrySignal(
            signal_type="short_liquidation",
            liquidation_usd=50_000.0,
            timestamp=datetime.now(timezone.utc),
            dominant_side="short_liquidated",
            long_usd=15_000.0,
            short_usd=35_000.0,
        )
        
        # Mock components
        bot._risk_controller.can_open_position = AsyncMock(return_value=(True, ""))
        bot._trade_logger.log_signal = AsyncMock()
        
        cancelled_order = PolymarketOrder(
            order_id="test-order",
            market_id="btc-5min-binary",
            outcome="UP",
            side="BUY",
            size=10.0,
            price=0.45,
            status="cancelled",
            fill_price=None,
            fill_time=None,
        )
        bot._polymarket_connector.place_order = AsyncMock(return_value=cancelled_order)
        
        await bot._handle_signal(signal)
        
        # Should place UP order
        bot._polymarket_connector.place_order.assert_called_once()
        call_args = bot._polymarket_connector.place_order.call_args
        assert call_args.kwargs["outcome"] == "UP"


class TestTradingBotHandlePolymarketFill:
    """Tests for Polymarket fill handling."""
    
    @pytest.fixture
    def filled_order(self):
        """Create a filled Polymarket order."""
        return PolymarketOrder(
            order_id="test-order",
            market_id="btc-5min-binary",
            outcome="UP",
            side="BUY",
            size=10.0,
            price=0.45,
            status="filled",
            fill_price=0.45,
            fill_time=datetime.now(timezone.utc),
        )
    
    @pytest.mark.asyncio
    async def test_handle_fill_opens_short_hedge_for_up_outcome(
        self, trading_config, mock_collector, filled_order
    ):
        """UP outcome on Polymarket should open SHORT hedge on Binance."""
        bot = TradingBot(config=trading_config, collector=mock_collector)
        
        # Mock components
        binance_position = BinancePosition(
            position_id="test-position",
            symbol="BTCUSDT",
            side="SHORT",
            size=0.001,
            leverage=3,
            entry_price=50000.0,
            margin_mode="isolated",
            status="open",
            pnl=None,
        )
        bot._binance_trader.open_position = AsyncMock(return_value=binance_position)
        bot._trade_logger.log_order_filled = AsyncMock()
        
        await bot._handle_polymarket_fill(filled_order)
        
        # Should open SHORT position
        bot._binance_trader.open_position.assert_called_once()
        call_args = bot._binance_trader.open_position.call_args
        assert call_args.kwargs["side"] == "SHORT"
    
    @pytest.mark.asyncio
    async def test_handle_fill_opens_long_hedge_for_down_outcome(
        self, trading_config, mock_collector
    ):
        """DOWN outcome on Polymarket should open LONG hedge on Binance."""
        bot = TradingBot(config=trading_config, collector=mock_collector)
        
        filled_order = PolymarketOrder(
            order_id="test-order",
            market_id="btc-5min-binary",
            outcome="DOWN",
            side="BUY",
            size=10.0,
            price=0.45,
            status="filled",
            fill_price=0.45,
            fill_time=datetime.now(timezone.utc),
        )
        
        # Mock components
        binance_position = BinancePosition(
            position_id="test-position",
            symbol="BTCUSDT",
            side="LONG",
            size=0.001,
            leverage=3,
            entry_price=50000.0,
            margin_mode="isolated",
            status="open",
            pnl=None,
        )
        bot._binance_trader.open_position = AsyncMock(return_value=binance_position)
        bot._trade_logger.log_order_filled = AsyncMock()
        
        await bot._handle_polymarket_fill(filled_order)
        
        # Should open LONG position
        bot._binance_trader.open_position.assert_called_once()
        call_args = bot._binance_trader.open_position.call_args
        assert call_args.kwargs["side"] == "LONG"
    
    @pytest.mark.asyncio
    async def test_handle_fill_blocks_new_signals(
        self, trading_config, mock_collector, filled_order
    ):
        """After fill, signal detector should block new signals."""
        bot = TradingBot(config=trading_config, collector=mock_collector)
        
        # Mock components
        binance_position = BinancePosition(
            position_id="test-position",
            symbol="BTCUSDT",
            side="SHORT",
            size=0.001,
            leverage=3,
            entry_price=50000.0,
            margin_mode="isolated",
            status="open",
            pnl=None,
        )
        bot._binance_trader.open_position = AsyncMock(return_value=binance_position)
        bot._trade_logger.log_order_filled = AsyncMock()
        
        # Initially signals should be allowed
        assert bot._signal_detector._position_open is False
        
        await bot._handle_polymarket_fill(filled_order)
        
        # After fill, signals should be blocked
        assert bot._signal_detector._position_open is True

    @pytest.mark.asyncio
    async def test_handle_fill_sends_reference_entry_price_in_notification(
        self, trading_config, mock_collector, filled_order
    ):
        """Trade entry notification should include BTC reference entry price when captured."""
        bot = TradingBot(config=trading_config, collector=mock_collector)

        bot._config.hedge_enabled = False
        bot._binance_trader.get_current_price = AsyncMock(return_value=50000.0)
        bot._trade_logger.log_order_filled = AsyncMock()
        bot._telegram_notifier = AsyncMock()

        await bot._handle_polymarket_fill(filled_order)

        bot._telegram_notifier.send_trade_entry.assert_called_once_with(
            trade_id=bot._position_manager.get_open_position().trade_id,
            direction=filled_order.outcome,
            entry_price=filled_order.fill_price or filled_order.price,
            bet_size=filled_order.size,
            reference_entry_price=50000.0,
            shares_bought=filled_order.shares_bought,
            max_profit=filled_order.max_profit,
            max_loss=filled_order.max_loss,
        )


class TestTradingBotHandlePositionClosed:
    """Tests for position closed callback."""
    
    @pytest.fixture
    def closed_trade_pair(self):
        """Create a closed trade pair."""
        polymarket_order = PolymarketOrder(
            order_id="test-order",
            market_id="btc-5min-binary",
            outcome="UP",
            side="BUY",
            size=10.0,
            price=0.45,
            status="filled",
            fill_price=0.45,
            fill_time=datetime.now(timezone.utc),
        )
        binance_position = BinancePosition(
            position_id="test-position",
            symbol="BTCUSDT",
            side="SHORT",
            size=0.001,
            leverage=3,
            entry_price=50000.0,
            margin_mode="isolated",
            status="closed",
            pnl=5.0,
        )
        return TradePair(
            trade_id="test-trade",
            polymarket_order=polymarket_order,
            binance_position=binance_position,
            direction="UP",
            entry_time=datetime.now(timezone.utc),
            expiry_time=datetime.now(timezone.utc),
            status="closed",
            polymarket_pnl=None,
            binance_pnl=5.0,
            total_pnl=5.0,
        )
    
    @pytest.mark.asyncio
    async def test_handle_position_closed_records_pnl(
        self, trading_config, mock_collector, closed_trade_pair
    ):
        """Position closed callback should record PnL with risk controller."""
        bot = TradingBot(config=trading_config, collector=mock_collector)
        
        # Mock trade logger
        bot._trade_logger.log_position_closed = AsyncMock()
        
        await bot._handle_position_closed(closed_trade_pair)
        
        # Should record PnL
        assert bot._risk_controller.get_daily_pnl() == 5.0
    
    @pytest.mark.asyncio
    async def test_handle_position_closed_enables_signals(
        self, trading_config, mock_collector, closed_trade_pair
    ):
        """Position closed callback should enable new signals."""
        bot = TradingBot(config=trading_config, collector=mock_collector)
        
        # Mock trade logger
        bot._trade_logger.log_position_closed = AsyncMock()
        
        # Block signals first
        bot._signal_detector.set_position_open(True)
        assert bot._signal_detector._position_open is True
        
        await bot._handle_position_closed(closed_trade_pair)
        
        # Signals should be enabled
        assert bot._signal_detector._position_open is False
    
    @pytest.mark.asyncio
    async def test_handle_position_closed_logs_close(
        self, trading_config, mock_collector, closed_trade_pair
    ):
        """Position closed callback should log the close event."""
        bot = TradingBot(config=trading_config, collector=mock_collector)
        
        # Mock trade logger
        bot._trade_logger.log_position_closed = AsyncMock()
        
        await bot._handle_position_closed(closed_trade_pair)
        
        # Should log position close
        bot._trade_logger.log_position_closed.assert_called_once_with(
            trade_id="test-trade",
            exchange="binance",
            pnl=5.0,
            is_dry_run=True,
        )

    @pytest.mark.asyncio
    async def test_handle_position_closed_logs_polymarket_when_no_hedge(
        self, trading_config, mock_collector
    ):
        """Position close should log Polymarket PnL when hedge is absent."""
        bot = TradingBot(config=trading_config, collector=mock_collector)
        bot._trade_logger.log_position_closed = AsyncMock()

        polymarket_order = PolymarketOrder(
            order_id="test-order",
            market_id="btc-5min-binary",
            outcome="UP",
            side="BUY",
            size=10.0,
            price=0.45,
            status="filled",
            fill_price=0.45,
            fill_time=datetime.now(timezone.utc),
            shares_bought=10.0 / 0.45,
            max_profit=(10.0 / 0.45) - 10.0,
            max_loss=10.0,
        )
        closed_trade_pair = TradePair(
            trade_id="test-trade-no-hedge",
            polymarket_order=polymarket_order,
            binance_position=None,
            direction="UP",
            entry_time=datetime.now(timezone.utc),
            expiry_time=datetime.now(timezone.utc),
            status="closed",
            polymarket_pnl=12.22,
            binance_pnl=None,
            total_pnl=12.22,
        )

        await bot._handle_position_closed(closed_trade_pair)

        bot._trade_logger.log_position_closed.assert_called_once_with(
            trade_id="test-trade-no-hedge",
            exchange="polymarket",
            pnl=12.22,
            is_dry_run=True,
        )

    @pytest.mark.asyncio
    async def test_handle_position_closed_sends_reference_prices(
        self, trading_config, mock_collector
    ):
        """Trade close notification should include stored BTC entry and exit prices."""
        bot = TradingBot(config=trading_config, collector=mock_collector)
        bot._trade_logger.log_position_closed = AsyncMock()
        bot._telegram_notifier = AsyncMock()

        polymarket_order = PolymarketOrder(
            order_id="test-order",
            market_id="btc-5min-binary",
            outcome="UP",
            side="BUY",
            size=10.0,
            price=0.45,
            status="filled",
            fill_price=0.45,
            fill_time=datetime.now(timezone.utc),
        )
        closed_trade_pair = TradePair(
            trade_id="test-trade-reference-prices",
            polymarket_order=polymarket_order,
            binance_position=None,
            direction="UP",
            entry_time=datetime.now(timezone.utc),
            expiry_time=datetime.now(timezone.utc),
            status="closed",
            polymarket_pnl=12.22,
            binance_pnl=None,
            total_pnl=12.22,
            reference_entry_price=50000.0,
            reference_exit_price=51000.0,
        )

        await bot._handle_position_closed(closed_trade_pair)

        bot._telegram_notifier.send_trade_closed.assert_called_once_with(
            trade_id="test-trade-reference-prices",
            polymarket_pnl=12.22,
            binance_pnl=None,
            total_pnl=12.22,
            daily_pnl=12.22,
            reference_entry_price=50000.0,
            reference_exit_price=51000.0,
        )


class TestTradingBotShutdown:
    """Tests for graceful shutdown."""
    
    @pytest.mark.asyncio
    async def test_shutdown_stops_signal_detector(
        self, trading_config, mock_collector
    ):
        """Shutdown should stop the signal detector."""
        bot = TradingBot(config=trading_config, collector=mock_collector)
        bot._running = True
        
        # Mock components
        bot._signal_detector.stop = AsyncMock()
        bot._trade_logger.close = AsyncMock()
        bot._polymarket_connector.close = AsyncMock()
        bot._binance_trader.close = AsyncMock()
        
        await bot.shutdown()
        
        # Should stop signal detector
        bot._signal_detector.stop.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_shutdown_flushes_trade_logs(
        self, trading_config, mock_collector
    ):
        """Shutdown should flush trade logs."""
        bot = TradingBot(config=trading_config, collector=mock_collector)
        bot._running = True
        
        # Mock components
        bot._signal_detector.stop = AsyncMock()
        bot._trade_logger.close = AsyncMock()
        bot._polymarket_connector.close = AsyncMock()
        bot._binance_trader.close = AsyncMock()
        
        await bot.shutdown()
        
        # Should close trade logger (which flushes)
        bot._trade_logger.close.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_shutdown_closes_exchange_connections(
        self, trading_config, mock_collector
    ):
        """Shutdown should close exchange connections."""
        bot = TradingBot(config=trading_config, collector=mock_collector)
        bot._running = True
        
        # Mock components
        bot._signal_detector.stop = AsyncMock()
        bot._trade_logger.close = AsyncMock()
        bot._polymarket_connector.close = AsyncMock()
        bot._binance_trader.close = AsyncMock()
        
        await bot.shutdown()
        
        # Should close both connectors
        bot._polymarket_connector.close.assert_called_once()
        bot._binance_trader.close.assert_called_once()
