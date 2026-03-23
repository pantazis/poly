"""Tests for BinanceTrader class."""

import asyncio
import hashlib
import hmac
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.trading.binance_trader import BinanceTrader
from src.trading.models import BinancePosition


class TestBinanceTraderInit:
    """Tests for BinanceTrader initialization."""
    
    def test_init_with_defaults(self):
        """Test initialization with default values."""
        trader = BinanceTrader(
            api_key="test_key",
            api_secret="test_secret",
        )
        
        assert trader.api_key == "test_key"
        assert trader.api_secret == "test_secret"
        assert trader.api_url == "https://fapi.binance.com"
        assert trader.dry_run is True
        assert trader._use_live_market_data_in_dry_run is False
    
    def test_init_with_custom_values(self):
        """Test initialization with custom values."""
        trader = BinanceTrader(
            api_key="my_key",
            api_secret="my_secret",
            api_url="https://testnet.binancefuture.com/",
            dry_run=False,
        )
        
        assert trader.api_key == "my_key"
        assert trader.api_secret == "my_secret"
        assert trader.api_url == "https://testnet.binancefuture.com"  # Trailing slash removed
        assert trader.dry_run is False
    
    def test_init_strips_trailing_slash(self):
        """Test that trailing slash is stripped from api_url."""
        trader = BinanceTrader(
            api_key="key",
            api_secret="secret",
            api_url="https://api.example.com///",
        )
        
        assert trader.api_url == "https://api.example.com"


class TestSignatureGeneration:
    """Tests for HMAC SHA256 signature generation."""
    
    def test_generate_signature(self):
        """Test signature generation matches expected HMAC SHA256."""
        trader = BinanceTrader(
            api_key="test_key",
            api_secret="test_secret",
        )
        
        query_string = "symbol=BTCUSDT&timestamp=1234567890"
        signature = trader._generate_signature(query_string)
        
        # Verify it's a valid hex string
        assert len(signature) == 64
        assert all(c in "0123456789abcdef" for c in signature)
        
        # Verify it matches expected HMAC
        expected = hmac.new(
            b"test_secret",
            query_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        
        assert signature == expected
    
    def test_signature_changes_with_different_secret(self):
        """Test that different secrets produce different signatures."""
        trader1 = BinanceTrader(api_key="key", api_secret="secret1")
        trader2 = BinanceTrader(api_key="key", api_secret="secret2")
        
        query = "test=value"
        sig1 = trader1._generate_signature(query)
        sig2 = trader2._generate_signature(query)
        
        assert sig1 != sig2


class TestDryRunMode:
    """Tests for dry run mode behavior."""
    
    @pytest.mark.asyncio
    async def test_connect_dry_run(self):
        """Test connect returns True in dry run mode without API call."""
        trader = BinanceTrader(
            api_key="key",
            api_secret="secret",
            dry_run=True,
        )
        
        result = await trader.connect()
        
        assert result is True
    
    @pytest.mark.asyncio
    async def test_get_available_margin_dry_run(self):
        """Test get_available_margin returns simulated value in dry run."""
        trader = BinanceTrader(
            api_key="key",
            api_secret="secret",
            dry_run=True,
        )
        
        margin = await trader.get_available_margin()
        
        assert margin == 1000.0
    
    @pytest.mark.asyncio
    async def test_get_current_price_dry_run(self):
        """Test get_current_price returns simulated value in dry run."""
        trader = BinanceTrader(
            api_key="key",
            api_secret="secret",
            dry_run=True,
        )
        
        price = await trader.get_current_price("BTCUSDT")
        
        assert price == 50000.0  # Default simulated price

    @pytest.mark.asyncio
    async def test_get_current_price_dry_run_uses_live_api_when_enabled(self):
        """Dry run should use live public price data when explicitly enabled."""
        trader = BinanceTrader(
            api_key="key",
            api_secret="secret",
            dry_run=True,
            use_live_market_data_in_dry_run=True,
        )

        trader._public_request = AsyncMock(return_value={"markPrice": "50321.5"})

        price = await trader.get_current_price("BTCUSDT")

        assert price == 50321.5
        trader._public_request.assert_awaited_once_with(
            "/fapi/v1/premiumIndex",
            {"symbol": "BTCUSDT"}
        )
    
    @pytest.mark.asyncio
    async def test_set_leverage_dry_run(self):
        """Test set_leverage returns True in dry run mode."""
        trader = BinanceTrader(
            api_key="key",
            api_secret="secret",
            dry_run=True,
        )
        
        result = await trader.set_leverage("BTCUSDT", 5)
        
        assert result is True
    
    @pytest.mark.asyncio
    async def test_set_margin_mode_dry_run(self):
        """Test set_margin_mode returns True in dry run mode."""
        trader = BinanceTrader(
            api_key="key",
            api_secret="secret",
            dry_run=True,
        )
        
        result = await trader.set_margin_mode("BTCUSDT", "isolated")
        
        assert result is True


class TestOpenPositionDryRun:
    """Tests for open_position in dry run mode."""
    
    @pytest.mark.asyncio
    async def test_open_long_position_dry_run(self):
        """Test opening a LONG position in dry run mode."""
        trader = BinanceTrader(
            api_key="key",
            api_secret="secret",
            dry_run=True,
        )
        
        position = await trader.open_position(
            side="LONG",
            size_usd=100.0,
            leverage=3,
        )
        
        assert isinstance(position, BinancePosition)
        assert position.side == "LONG"
        assert position.symbol == "BTCUSDT"
        assert position.leverage == 3
        assert position.margin_mode == "isolated"
        assert position.status == "open"
        assert position.pnl is None
        assert position.entry_price == 50000.0  # Simulated price
        
        # Position size = (100 / 50000) * 3 = 0.006
        assert position.size == 0.006
    
    @pytest.mark.asyncio
    async def test_open_short_position_dry_run(self):
        """Test opening a SHORT position in dry run mode."""
        trader = BinanceTrader(
            api_key="key",
            api_secret="secret",
            dry_run=True,
        )
        
        position = await trader.open_position(
            side="SHORT",
            size_usd=150.0,
            leverage=5,
        )
        
        assert position.side == "SHORT"
        assert position.leverage == 5
        assert position.status == "open"
        
        # Position size = (150 / 50000) * 5 = 0.015
        assert position.size == 0.015
    
    @pytest.mark.asyncio
    async def test_position_size_calculation(self):
        """Test position size calculation: (size_usd / price) * leverage."""
        trader = BinanceTrader(
            api_key="key",
            api_secret="secret",
            dry_run=True,
        )
        
        # Set a custom simulated price
        trader._simulated_price = 40000.0
        
        position = await trader.open_position(
            side="LONG",
            size_usd=200.0,
            leverage=3,
        )
        
        # Position size = (200 / 40000) * 3 = 0.015
        expected_size = round((200.0 / 40000.0) * 3, 3)
        assert position.size == expected_size
    
    @pytest.mark.asyncio
    async def test_position_has_unique_id(self):
        """Test that each position gets a unique ID."""
        trader = BinanceTrader(
            api_key="key",
            api_secret="secret",
            dry_run=True,
        )
        
        pos1 = await trader.open_position(side="LONG", size_usd=100.0)
        pos2 = await trader.open_position(side="SHORT", size_usd=100.0)
        
        assert pos1.position_id != pos2.position_id


class TestClosePositionDryRun:
    """Tests for close_position in dry run mode."""
    
    @pytest.mark.asyncio
    async def test_close_position_dry_run(self):
        """Test closing a position in dry run mode."""
        trader = BinanceTrader(
            api_key="key",
            api_secret="secret",
            dry_run=True,
        )
        
        # Open a position first
        position = await trader.open_position(
            side="LONG",
            size_usd=100.0,
            leverage=3,
        )
        
        # Close the position
        closed = await trader.close_position(position.position_id)
        
        assert closed.status == "closed"
        assert closed.pnl is not None
        assert closed.position_id == position.position_id
        assert closed.side == position.side
        assert closed.size == position.size
    
    @pytest.mark.asyncio
    async def test_close_nonexistent_position_raises(self):
        """Test closing a non-existent position raises ValueError."""
        trader = BinanceTrader(
            api_key="key",
            api_secret="secret",
            dry_run=True,
        )
        
        with pytest.raises(ValueError, match="not found"):
            await trader.close_position("nonexistent-id")
    
    @pytest.mark.asyncio
    async def test_close_removes_position_from_tracking(self):
        """Test that closing removes position from internal tracking."""
        trader = BinanceTrader(
            api_key="key",
            api_secret="secret",
            dry_run=True,
        )
        
        position = await trader.open_position(side="LONG", size_usd=100.0)
        position_id = position.position_id
        
        assert position_id in trader._simulated_positions
        
        await trader.close_position(position_id)
        
        assert position_id not in trader._simulated_positions


class TestOpenPositionRetry:
    """Tests for open_position retry logic."""
    
    @pytest.mark.asyncio
    async def test_retry_on_failure(self):
        """Test that open_position retries on failure."""
        trader = BinanceTrader(
            api_key="key",
            api_secret="secret",
            dry_run=False,
        )
        
        order_call_count = 0
        
        async def mock_signed_request(method, endpoint, params=None):
            nonlocal order_call_count
            
            if endpoint == "/fapi/v1/leverage":
                return {}
            elif endpoint == "/fapi/v1/marginType":
                return {}
            elif endpoint == "/fapi/v1/order":
                order_call_count += 1
                if order_call_count < 3:  # Fail first 2 attempts
                    raise ValueError("Simulated failure")
                return {
                    "orderId": "12345",
                    "avgPrice": "50000.0",
                }
            return {}
        
        async def mock_public_request(endpoint, params=None):
            if endpoint == "/fapi/v1/premiumIndex":
                return {"markPrice": "50000.0"}
            return {}
        
        trader._signed_request = mock_signed_request
        trader._public_request = mock_public_request
        
        position = await trader.open_position(
            side="LONG",
            size_usd=100.0,
            leverage=3,
            max_retries=3,
        )
        
        assert position is not None
        assert position.status == "open"
    
    @pytest.mark.asyncio
    async def test_raises_after_max_retries(self):
        """Test that ValueError is raised after max retries exhausted."""
        trader = BinanceTrader(
            api_key="key",
            api_secret="secret",
            dry_run=False,
        )
        
        async def mock_signed_request(method, endpoint, params=None):
            if endpoint == "/fapi/v1/leverage":
                return {}
            elif endpoint == "/fapi/v1/marginType":
                return {}
            elif endpoint == "/fapi/v1/order":
                raise ValueError("Persistent failure")
            return {}
        
        async def mock_public_request(endpoint, params=None):
            if endpoint == "/fapi/v1/premiumIndex":
                return {"markPrice": "50000.0"}
            return {}
        
        trader._signed_request = mock_signed_request
        trader._public_request = mock_public_request
        
        with pytest.raises(ValueError, match="Failed to open position after 3 attempts"):
            await trader.open_position(
                side="LONG",
                size_usd=100.0,
                max_retries=3,
            )


class TestLiveMode:
    """Tests for live mode (non-dry-run) behavior with mocked API."""
    
    @pytest.mark.asyncio
    async def test_connect_live_success(self):
        """Test connect in live mode with successful API response."""
        trader = BinanceTrader(
            api_key="key",
            api_secret="secret",
            dry_run=False,
        )
        
        async def mock_signed_request(method, endpoint, params=None):
            return {"canTrade": True}
        
        trader._signed_request = mock_signed_request
        
        result = await trader.connect()
        
        assert result is True
    
    @pytest.mark.asyncio
    async def test_connect_live_no_trade_permission(self):
        """Test connect fails when API key lacks trading permission."""
        trader = BinanceTrader(
            api_key="key",
            api_secret="secret",
            dry_run=False,
        )
        
        async def mock_signed_request(method, endpoint, params=None):
            return {"canTrade": False}
        
        trader._signed_request = mock_signed_request
        
        result = await trader.connect()
        
        assert result is False
    
    @pytest.mark.asyncio
    async def test_get_available_margin_live(self):
        """Test get_available_margin in live mode."""
        trader = BinanceTrader(
            api_key="key",
            api_secret="secret",
            dry_run=False,
        )
        
        async def mock_signed_request(method, endpoint, params=None):
            return {
                "assets": [
                    {"asset": "BTC", "availableBalance": "0.5"},
                    {"asset": "USDT", "availableBalance": "1500.50"},
                ]
            }
        
        trader._signed_request = mock_signed_request
        
        margin = await trader.get_available_margin()
        
        assert margin == 1500.50
    
    @pytest.mark.asyncio
    async def test_get_current_price_live(self):
        """Test get_current_price in live mode."""
        trader = BinanceTrader(
            api_key="key",
            api_secret="secret",
            dry_run=False,
        )
        
        async def mock_public_request(endpoint, params=None):
            return {"markPrice": "67500.25"}
        
        trader._public_request = mock_public_request
        
        price = await trader.get_current_price("BTCUSDT")
        
        assert price == 67500.25
