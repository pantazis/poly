"""Tests for the PositionManager class."""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.trading.binance_trader import BinanceTrader
from src.trading.models import BinancePosition, PolymarketOrder, TradePair
from src.trading.position_manager import PositionManager


@pytest.fixture
def mock_binance_trader():
    """Create a mock BinanceTrader."""
    trader = MagicMock(spec=BinanceTrader)
    trader.close_position = AsyncMock()
    trader.get_current_price = AsyncMock(return_value=50000.0)
    trader.dry_run = False
    return trader


@pytest.fixture
def sample_polymarket_order():
    """Create a sample PolymarketOrder."""
    return PolymarketOrder(
        order_id="pm-order-123",
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


@pytest.fixture
def sample_binance_position():
    """Create a sample BinancePosition."""
    return BinancePosition(
        position_id="bn-pos-456",
        symbol="BTCUSDT",
        side="SHORT",
        size=0.001,
        leverage=3,
        entry_price=50000.0,
        margin_mode="isolated",
        status="open",
        pnl=None,
    )


class TestPositionManagerInit:
    """Tests for PositionManager initialization."""

    def test_init_with_binance_trader(self, mock_binance_trader):
        """Test initialization with binance_trader reference."""
        manager = PositionManager(binance_trader=mock_binance_trader)
        
        assert manager._binance_trader is mock_binance_trader
        assert manager._on_position_closed is None
        assert manager._open_position is None
        assert manager._all_trades == []

    def test_init_with_callback(self, mock_binance_trader):
        """Test initialization with on_position_closed callback."""
        callback = AsyncMock()
        manager = PositionManager(
            binance_trader=mock_binance_trader,
            on_position_closed=callback,
        )
        
        assert manager._on_position_closed is callback


class TestHasOpenPosition:
    """Tests for has_open_position method."""

    def test_no_open_position(self, mock_binance_trader):
        """Test returns False when no position is open."""
        manager = PositionManager(binance_trader=mock_binance_trader)
        
        assert manager.has_open_position() is False

    @pytest.mark.asyncio
    async def test_with_open_position(
        self, mock_binance_trader, sample_polymarket_order, sample_binance_position
    ):
        """Test returns True when a position is open."""
        manager = PositionManager(binance_trader=mock_binance_trader)
        
        await manager.open_trade_pair(sample_polymarket_order, sample_binance_position)
        
        assert manager.has_open_position() is True


class TestGetOpenPosition:
    """Tests for get_open_position method."""

    def test_no_open_position(self, mock_binance_trader):
        """Test returns None when no position is open."""
        manager = PositionManager(binance_trader=mock_binance_trader)
        
        assert manager.get_open_position() is None

    @pytest.mark.asyncio
    async def test_with_open_position(
        self, mock_binance_trader, sample_polymarket_order, sample_binance_position
    ):
        """Test returns the open TradePair."""
        manager = PositionManager(binance_trader=mock_binance_trader)
        
        trade_pair = await manager.open_trade_pair(
            sample_polymarket_order, sample_binance_position
        )
        
        assert manager.get_open_position() is trade_pair


class TestOpenTradePair:
    """Tests for open_trade_pair method."""

    @pytest.mark.asyncio
    async def test_creates_trade_pair_with_uuid(
        self, mock_binance_trader, sample_polymarket_order, sample_binance_position
    ):
        """Test creates TradePair with valid UUID trade_id."""
        manager = PositionManager(binance_trader=mock_binance_trader)
        
        trade_pair = await manager.open_trade_pair(
            sample_polymarket_order, sample_binance_position
        )
        
        # Verify UUID format (8-4-4-4-12 hex digits)
        import uuid
        uuid.UUID(trade_pair.trade_id)  # Raises if invalid

    @pytest.mark.asyncio
    async def test_sets_entry_time_to_utc(
        self, mock_binance_trader, sample_polymarket_order, sample_binance_position
    ):
        """Test sets entry_time to current UTC time."""
        manager = PositionManager(binance_trader=mock_binance_trader)
        
        before = datetime.now(timezone.utc)
        trade_pair = await manager.open_trade_pair(
            sample_polymarket_order, sample_binance_position
        )
        after = datetime.now(timezone.utc)
        
        assert before <= trade_pair.entry_time <= after
        assert trade_pair.entry_time.tzinfo == timezone.utc

    @pytest.mark.asyncio
    async def test_sets_expiry_time_to_entry_plus_5_minutes(
        self, mock_binance_trader, sample_polymarket_order, sample_binance_position
    ):
        """Test sets expiry_time to entry_time + 5 minutes."""
        manager = PositionManager(binance_trader=mock_binance_trader)
        
        trade_pair = await manager.open_trade_pair(
            sample_polymarket_order, sample_binance_position
        )
        
        expected_expiry = trade_pair.entry_time + timedelta(minutes=5)
        assert trade_pair.expiry_time == expected_expiry

    @pytest.mark.asyncio
    async def test_sets_status_to_open(
        self, mock_binance_trader, sample_polymarket_order, sample_binance_position
    ):
        """Test sets status to 'open'."""
        manager = PositionManager(binance_trader=mock_binance_trader)
        
        trade_pair = await manager.open_trade_pair(
            sample_polymarket_order, sample_binance_position
        )
        
        assert trade_pair.status == "open"

    @pytest.mark.asyncio
    async def test_sets_direction_from_polymarket_outcome(
        self, mock_binance_trader, sample_binance_position
    ):
        """Test sets direction from Polymarket order outcome."""
        manager = PositionManager(binance_trader=mock_binance_trader)
        
        # Test UP outcome
        up_order = PolymarketOrder(
            order_id="pm-1",
            market_id="btc-5min",
            outcome="UP",
            side="BUY",
            size=10.0,
            price=0.45,
            status="filled",
            fill_price=0.45,
            fill_time=datetime.now(timezone.utc),
        )
        trade_pair = await manager.open_trade_pair(up_order, sample_binance_position)
        assert trade_pair.direction == "UP"

    @pytest.mark.asyncio
    async def test_handles_none_binance_position(
        self, mock_binance_trader, sample_polymarket_order
    ):
        """Test handles None binance_position (hedge failed)."""
        manager = PositionManager(binance_trader=mock_binance_trader)
        
        trade_pair = await manager.open_trade_pair(
            sample_polymarket_order, None
        )
        
        assert trade_pair.binance_position is None
        assert trade_pair.status == "open"

    @pytest.mark.asyncio
    async def test_adds_to_all_trades(
        self, mock_binance_trader, sample_polymarket_order, sample_binance_position
    ):
        """Test adds trade pair to all_trades list."""
        manager = PositionManager(binance_trader=mock_binance_trader)
        
        trade_pair = await manager.open_trade_pair(
            sample_polymarket_order, sample_binance_position
        )
        
        assert trade_pair in manager.get_all_trades()


class TestCloseTradePair:
    """Tests for close_trade_pair method."""

    @pytest.mark.asyncio
    async def test_closes_binance_position(
        self, mock_binance_trader, sample_polymarket_order, sample_binance_position
    ):
        """Test closes Binance hedge position via binance_trader."""
        closed_position = BinancePosition(
            position_id=sample_binance_position.position_id,
            symbol="BTCUSDT",
            side="SHORT",
            size=0.001,
            leverage=3,
            entry_price=50000.0,
            margin_mode="isolated",
            status="closed",
            pnl=5.0,
        )
        mock_binance_trader.close_position.return_value = closed_position
        
        manager = PositionManager(binance_trader=mock_binance_trader)
        trade_pair = await manager.open_trade_pair(
            sample_polymarket_order, sample_binance_position
        )
        
        closed_trade = await manager.close_trade_pair(trade_pair.trade_id)
        
        mock_binance_trader.close_position.assert_called_once_with(
            sample_binance_position.position_id
        )
        assert closed_trade.binance_pnl == 5.0

    @pytest.mark.asyncio
    async def test_sets_status_to_closed(
        self, mock_binance_trader, sample_polymarket_order, sample_binance_position
    ):
        """Test sets status to 'closed'."""
        mock_binance_trader.close_position.return_value = BinancePosition(
            position_id=sample_binance_position.position_id,
            symbol="BTCUSDT",
            side="SHORT",
            size=0.001,
            leverage=3,
            entry_price=50000.0,
            margin_mode="isolated",
            status="closed",
            pnl=0.0,
        )
        
        manager = PositionManager(binance_trader=mock_binance_trader)
        trade_pair = await manager.open_trade_pair(
            sample_polymarket_order, sample_binance_position
        )
        
        closed_trade = await manager.close_trade_pair(trade_pair.trade_id)
        
        assert closed_trade.status == "closed"

    @pytest.mark.asyncio
    async def test_calculates_total_pnl(
        self, mock_binance_trader, sample_polymarket_order, sample_binance_position
    ):
        """Test calculates total PnL (polymarket_pnl + binance_pnl)."""
        mock_binance_trader.close_position.return_value = BinancePosition(
            position_id=sample_binance_position.position_id,
            symbol="BTCUSDT",
            side="SHORT",
            size=0.001,
            leverage=3,
            entry_price=50000.0,
            margin_mode="isolated",
            status="closed",
            pnl=3.5,
        )
        
        manager = PositionManager(binance_trader=mock_binance_trader)
        trade_pair = await manager.open_trade_pair(
            sample_polymarket_order, sample_binance_position
        )
        # Simulate polymarket PnL being set
        trade_pair.polymarket_pnl = 8.0
        
        closed_trade = await manager.close_trade_pair(trade_pair.trade_id)
        
        assert closed_trade.total_pnl == 11.5  # 8.0 + 3.5

    @pytest.mark.asyncio
    async def test_calls_on_position_closed_callback(
        self, mock_binance_trader, sample_polymarket_order, sample_binance_position
    ):
        """Test calls on_position_closed callback if set."""
        mock_binance_trader.close_position.return_value = BinancePosition(
            position_id=sample_binance_position.position_id,
            symbol="BTCUSDT",
            side="SHORT",
            size=0.001,
            leverage=3,
            entry_price=50000.0,
            margin_mode="isolated",
            status="closed",
            pnl=0.0,
        )
        
        callback = AsyncMock()
        manager = PositionManager(
            binance_trader=mock_binance_trader,
            on_position_closed=callback,
        )
        trade_pair = await manager.open_trade_pair(
            sample_polymarket_order, sample_binance_position
        )
        
        closed_trade = await manager.close_trade_pair(trade_pair.trade_id)
        
        callback.assert_called_once_with(closed_trade)

    @pytest.mark.asyncio
    async def test_clears_open_position(
        self, mock_binance_trader, sample_polymarket_order, sample_binance_position
    ):
        """Test clears open position after closing."""
        mock_binance_trader.close_position.return_value = BinancePosition(
            position_id=sample_binance_position.position_id,
            symbol="BTCUSDT",
            side="SHORT",
            size=0.001,
            leverage=3,
            entry_price=50000.0,
            margin_mode="isolated",
            status="closed",
            pnl=0.0,
        )
        
        manager = PositionManager(binance_trader=mock_binance_trader)
        trade_pair = await manager.open_trade_pair(
            sample_polymarket_order, sample_binance_position
        )
        
        assert manager.has_open_position() is True
        
        await manager.close_trade_pair(trade_pair.trade_id)
        
        assert manager.has_open_position() is False

    @pytest.mark.asyncio
    async def test_raises_for_unknown_trade_id(self, mock_binance_trader):
        """Test raises ValueError for unknown trade_id."""
        manager = PositionManager(binance_trader=mock_binance_trader)
        
        with pytest.raises(ValueError, match="not found"):
            await manager.close_trade_pair("unknown-trade-id")

    @pytest.mark.asyncio
    async def test_raises_for_already_closed_trade(
        self, mock_binance_trader, sample_polymarket_order, sample_binance_position
    ):
        """Test raises ValueError for already closed trade."""
        mock_binance_trader.close_position.return_value = BinancePosition(
            position_id=sample_binance_position.position_id,
            symbol="BTCUSDT",
            side="SHORT",
            size=0.001,
            leverage=3,
            entry_price=50000.0,
            margin_mode="isolated",
            status="closed",
            pnl=0.0,
        )
        
        manager = PositionManager(binance_trader=mock_binance_trader)
        trade_pair = await manager.open_trade_pair(
            sample_polymarket_order, sample_binance_position
        )
        
        await manager.close_trade_pair(trade_pair.trade_id)
        
        with pytest.raises(ValueError, match="already closed"):
            await manager.close_trade_pair(trade_pair.trade_id)

    @pytest.mark.asyncio
    async def test_handles_none_binance_position_on_close(
        self, mock_binance_trader, sample_polymarket_order
    ):
        """Test handles closing trade with no Binance position."""
        manager = PositionManager(binance_trader=mock_binance_trader)
        trade_pair = await manager.open_trade_pair(sample_polymarket_order, None)
        
        closed_trade = await manager.close_trade_pair(trade_pair.trade_id)
        
        mock_binance_trader.close_position.assert_not_called()
        assert closed_trade.status == "closed"
        assert closed_trade.binance_pnl is None

    @pytest.mark.asyncio
    async def test_calculates_dry_run_polymarket_profit_for_up_win(
        self, mock_binance_trader, sample_polymarket_order
    ):
        """Dry-run UP trade should win when BTC is higher at expiry."""
        mock_binance_trader.dry_run = True
        mock_binance_trader.get_current_price = AsyncMock(return_value=51000.0)

        manager = PositionManager(binance_trader=mock_binance_trader)
        trade_pair = await manager.open_trade_pair(
            sample_polymarket_order,
            None,
            reference_entry_price=50000.0,
        )

        closed_trade = await manager.close_trade_pair(trade_pair.trade_id)

        assert closed_trade.polymarket_pnl == pytest.approx((10.0 / 0.45) - 10.0, rel=1e-3)
        assert closed_trade.total_pnl == closed_trade.polymarket_pnl
        assert closed_trade.reference_exit_price == 51000.0

    @pytest.mark.asyncio
    async def test_calculates_dry_run_polymarket_loss_for_down_loss(
        self, mock_binance_trader
    ):
        """Dry-run DOWN trade should lose the full stake when BTC rises."""
        mock_binance_trader.dry_run = True
        mock_binance_trader.get_current_price = AsyncMock(return_value=51000.0)

        down_order = PolymarketOrder(
            order_id="pm-order-down",
            market_id="btc-5min-binary",
            outcome="DOWN",
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

        manager = PositionManager(binance_trader=mock_binance_trader)
        trade_pair = await manager.open_trade_pair(
            down_order,
            None,
            reference_entry_price=50000.0,
        )

        closed_trade = await manager.close_trade_pair(trade_pair.trade_id)

        assert closed_trade.polymarket_pnl == -10.0
        assert closed_trade.total_pnl == -10.0


class TestCheckExpiries:
    """Tests for check_expiries method."""

    @pytest.mark.asyncio
    async def test_does_nothing_when_no_open_position(self, mock_binance_trader):
        """Test does nothing when no position is open."""
        manager = PositionManager(binance_trader=mock_binance_trader)
        
        await manager.check_expiries()
        
        mock_binance_trader.close_position.assert_not_called()

    @pytest.mark.asyncio
    async def test_closes_expired_position(
        self, mock_binance_trader, sample_polymarket_order, sample_binance_position
    ):
        """Test closes position when current time >= expiry_time."""
        mock_binance_trader.close_position.return_value = BinancePosition(
            position_id=sample_binance_position.position_id,
            symbol="BTCUSDT",
            side="SHORT",
            size=0.001,
            leverage=3,
            entry_price=50000.0,
            margin_mode="isolated",
            status="closed",
            pnl=0.0,
        )
        
        manager = PositionManager(binance_trader=mock_binance_trader)
        trade_pair = await manager.open_trade_pair(
            sample_polymarket_order, sample_binance_position
        )
        
        # Manually set expiry to past
        trade_pair.expiry_time = datetime.now(timezone.utc) - timedelta(seconds=1)
        
        await manager.check_expiries()
        
        mock_binance_trader.close_position.assert_called_once()
        assert manager.has_open_position() is False

    @pytest.mark.asyncio
    async def test_does_not_close_non_expired_position(
        self, mock_binance_trader, sample_polymarket_order, sample_binance_position
    ):
        """Test does not close position when current time < expiry_time."""
        manager = PositionManager(binance_trader=mock_binance_trader)
        await manager.open_trade_pair(
            sample_polymarket_order, sample_binance_position
        )
        
        # Position just opened, expiry is 5 minutes in future
        await manager.check_expiries()
        
        mock_binance_trader.close_position.assert_not_called()
        assert manager.has_open_position() is True


class TestGetAllTrades:
    """Tests for get_all_trades method."""

    def test_returns_empty_list_initially(self, mock_binance_trader):
        """Test returns empty list when no trades."""
        manager = PositionManager(binance_trader=mock_binance_trader)
        
        assert manager.get_all_trades() == []

    @pytest.mark.asyncio
    async def test_returns_all_trades(
        self, mock_binance_trader, sample_polymarket_order, sample_binance_position
    ):
        """Test returns all trades (open and closed)."""
        mock_binance_trader.close_position.return_value = BinancePosition(
            position_id=sample_binance_position.position_id,
            symbol="BTCUSDT",
            side="SHORT",
            size=0.001,
            leverage=3,
            entry_price=50000.0,
            margin_mode="isolated",
            status="closed",
            pnl=0.0,
        )
        
        manager = PositionManager(binance_trader=mock_binance_trader)
        
        # Open and close first trade
        trade1 = await manager.open_trade_pair(
            sample_polymarket_order, sample_binance_position
        )
        await manager.close_trade_pair(trade1.trade_id)
        
        # Open second trade
        trade2 = await manager.open_trade_pair(
            sample_polymarket_order, sample_binance_position
        )
        
        all_trades = manager.get_all_trades()
        
        assert len(all_trades) == 2
        assert trade1 in all_trades
        assert trade2 in all_trades

    @pytest.mark.asyncio
    async def test_returns_copy_of_list(
        self, mock_binance_trader, sample_polymarket_order, sample_binance_position
    ):
        """Test returns a copy of the trades list."""
        manager = PositionManager(binance_trader=mock_binance_trader)
        await manager.open_trade_pair(
            sample_polymarket_order, sample_binance_position
        )
        
        trades1 = manager.get_all_trades()
        trades2 = manager.get_all_trades()
        
        assert trades1 is not trades2
        assert trades1 == trades2
