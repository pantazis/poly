"""Unit tests for PolymarketConnector.

Tests the Polymarket CLOB API connector functionality including:
- Connection verification
- Balance retrieval
- Price fetching
- Order placement with discount calculation
- Order cancellation
- Dry run mode simulation
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from src.trading.polymarket_connector import PolymarketConnector
from src.trading.models import PolymarketOrder


class _FakeResponse:
    def __init__(self, status: int, payload: dict):
        self.status = status
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def json(self):
        return self._payload


class _FakeSession:
    def __init__(self, status: int, payload: dict):
        self._status = status
        self._payload = payload

    def get(self, *args, **kwargs):
        return _FakeResponse(self._status, self._payload)


class TestPolymarketConnectorInit:
    """Tests for PolymarketConnector initialization."""
    
    def test_init_with_defaults(self):
        """Test initialization with default values."""
        connector = PolymarketConnector(
            private_key="0" * 64,
            api_key="test-key",
            api_secret="test-secret",
            passphrase="test-pass",
        )
        
        assert connector._private_key == "0" * 64
        assert connector._api_key == "test-key"
        assert connector._api_secret == "test-secret"
        assert connector._passphrase == "test-pass"
        assert connector.CLOB_API_URL == "https://clob.polymarket.com"
        assert connector._dry_run is True
    
    def test_init_dry_run_false(self):
        """Test initialization with dry_run=False."""
        connector = PolymarketConnector(
            private_key="0" * 64,
            dry_run=False,
        )
        
        assert connector._dry_run is False

    def test_init_live_market_data_disabled_by_default(self):
        """Direct connector initialization keeps live dry-run data opt-in."""
        connector = PolymarketConnector(private_key="0" * 64)

        assert connector._use_live_market_data_in_dry_run is False
    
    def test_init_simulated_state(self):
        """Test that simulated state is initialized correctly."""
        connector = PolymarketConnector(private_key="0" * 64)
        
        assert connector._simulated_balance == 10000.0
        assert connector._simulated_prices == {"UP": 0.50, "DOWN": 0.50}
        assert connector._simulated_orders == {}


class TestPolymarketConnectorDryRun:
    """Tests for dry run mode functionality."""
    
    @pytest.fixture
    def connector(self):
        """Create a connector in dry run mode."""
        return PolymarketConnector(
            private_key="0" * 64,
            api_key="test-key",
            api_secret="test-secret",
            passphrase="test-pass",
            dry_run=True,
        )
    
    @pytest.mark.asyncio
    async def test_connect_dry_run(self, connector):
        """Test connection in dry run mode always succeeds."""
        result = await connector.connect()
        assert result is True
    
    @pytest.mark.asyncio
    async def test_get_balance_dry_run(self, connector):
        """Test balance retrieval in dry run mode."""
        balance = await connector.get_balance()
        assert balance == 10000.0
    
    @pytest.mark.asyncio
    async def test_get_balance_after_set(self, connector):
        """Test balance after setting simulated balance."""
        connector.set_simulated_balance(500.0)
        balance = await connector.get_balance()
        assert balance == 500.0
    
    @pytest.mark.asyncio
    async def test_get_current_price_up(self, connector):
        """Test getting UP outcome price."""
        price = await connector.get_current_price("UP")
        assert price == 0.50
    
    @pytest.mark.asyncio
    async def test_get_current_price_down(self, connector):
        """Test getting DOWN outcome price."""
        price = await connector.get_current_price("DOWN")
        assert price == 0.50
    
    @pytest.mark.asyncio
    async def test_get_current_price_custom(self, connector):
        """Test getting price after setting custom simulated price."""
        connector.set_simulated_price("UP", 0.65)
        price = await connector.get_current_price("UP")
        assert price == 0.65
    
    @pytest.mark.asyncio
    async def test_get_current_price_invalid_outcome(self, connector):
        """Test that invalid outcome raises ValueError."""
        with pytest.raises(ValueError, match="Invalid outcome"):
            await connector.get_current_price("INVALID")

    @pytest.mark.asyncio
    async def test_get_current_price_uses_live_api_when_enabled_in_dry_run(self):
        """Dry run can use read-only Polymarket pricing when explicitly enabled."""
        connector = PolymarketConnector(
            private_key="0" * 64,
            dry_run=True,
            use_live_market_data_in_dry_run=True,
        )
        connector._ensure_current_market = AsyncMock(return_value=True)
        connector._get_session = AsyncMock(return_value=_FakeSession(200, {"price": "0.61"}))
        connector._current_up_token_id = "up-token"

        price = await connector.get_current_price("UP")

        assert price == pytest.approx(0.61)

    @pytest.mark.asyncio
    async def test_get_current_price_falls_back_to_simulated_value_when_live_pricing_fails(self):
        """Dry run should log and use simulated fallback pricing when live lookup fails."""
        connector = PolymarketConnector(
            private_key="0" * 64,
            dry_run=True,
            use_live_market_data_in_dry_run=True,
        )
        connector.set_simulated_price("UP", 0.73)
        connector._ensure_current_market = AsyncMock(return_value=False)

        with patch("src.trading.polymarket_connector.logger.warning") as mock_warning:
            price = await connector.get_current_price("UP")

        assert price == pytest.approx(0.73)
        mock_warning.assert_called_once()
        assert "Falling back to simulated price 0.7300" in mock_warning.call_args[0][0]


class TestPolymarketOrderPlacement:
    """Tests for order placement functionality."""
    
    @pytest.fixture
    def connector(self):
        """Create a connector in dry run mode."""
        return PolymarketConnector(
            private_key="0" * 64,
            api_key="test-key",
            api_secret="test-secret",
            passphrase="test-pass",
            dry_run=True,
        )
    
    @pytest.mark.asyncio
    async def test_place_order_up(self, connector):
        """Test placing an UP order."""
        order = await connector.place_order(
            outcome="UP",
            size=10.0,
            discount_percent=10.0,
        )
        
        assert order.outcome == "UP"
        assert order.side == "BUY"
        assert order.size == 10.0
        assert order.status == "filled"
        assert order.fill_price is not None
        assert order.fill_time is not None
    
    @pytest.mark.asyncio
    async def test_place_order_down(self, connector):
        """Test placing a DOWN order."""
        order = await connector.place_order(
            outcome="DOWN",
            size=15.0,
            discount_percent=5.0,
        )
        
        assert order.outcome == "DOWN"
        assert order.side == "BUY"
        assert order.size == 15.0
        assert order.status == "filled"
    
    @pytest.mark.asyncio
    async def test_place_order_discount_calculation(self, connector):
        """Test that limit price is calculated with correct discount."""
        connector.set_simulated_price("UP", 0.60)
        
        order = await connector.place_order(
            outcome="UP",
            size=10.0,
            discount_percent=10.0,
        )
        
        # Expected price: 0.60 * (1 - 10/100) = 0.60 * 0.90 = 0.54
        expected_price = 0.60 * (1 - 10.0 / 100)
        assert abs(order.price - expected_price) < 0.0001
    
    @pytest.mark.asyncio
    async def test_place_order_zero_discount(self, connector):
        """Test order with zero discount."""
        connector.set_simulated_price("DOWN", 0.45)
        
        order = await connector.place_order(
            outcome="DOWN",
            size=10.0,
            discount_percent=0.0,
        )
        
        assert abs(order.price - 0.45) < 0.0001
    
    @pytest.mark.asyncio
    async def test_place_order_large_discount(self, connector):
        """Test order with large discount stays within bounds."""
        connector.set_simulated_price("UP", 0.10)
        
        order = await connector.place_order(
            outcome="UP",
            size=10.0,
            discount_percent=95.0,  # Would result in 0.005, below minimum
        )
        
        # Price should be clamped to minimum of 0.01
        assert order.price >= 0.01
    
    @pytest.mark.asyncio
    async def test_place_order_invalid_outcome(self, connector):
        """Test that invalid outcome raises ValueError."""
        with pytest.raises(ValueError, match="Invalid outcome"):
            await connector.place_order(
                outcome="SIDEWAYS",
                size=10.0,
            )
    
    @pytest.mark.asyncio
    async def test_place_order_updates_balance(self, connector):
        """Test that placing order deducts from simulated balance."""
        initial_balance = await connector.get_balance()
        
        await connector.place_order(
            outcome="UP",
            size=100.0,
        )
        
        new_balance = await connector.get_balance()
        assert new_balance == initial_balance - 100.0

    @pytest.mark.asyncio
    async def test_place_order_calculates_bet_statistics(self, connector):
        """Test dry-run order includes bet statistics derived from fill price."""
        connector.set_simulated_price("UP", 0.50)

        order = await connector.place_order(
            outcome="UP",
            size=10.0,
            discount_percent=10.0,
        )

        assert order.fill_price == pytest.approx(0.45)
        assert order.shares_bought == pytest.approx(10.0 / 0.45)
        assert order.max_profit == pytest.approx((10.0 / 0.45) - 10.0)
        assert order.max_loss == pytest.approx(10.0)

    @pytest.mark.asyncio
    async def test_place_order_uses_live_polymarket_price_when_enabled_in_dry_run(self):
        """Dry-run order calculations should derive from live read-only Polymarket price when enabled."""
        connector = PolymarketConnector(
            private_key="0" * 64,
            dry_run=True,
            use_live_market_data_in_dry_run=True,
        )
        connector._ensure_current_market = AsyncMock(return_value=True)
        connector._get_session = AsyncMock(return_value=_FakeSession(200, {"price": "0.61"}))
        connector._current_up_token_id = "up-token"
        connector._current_market_id = "market-123"

        order = await connector.place_order(
            outcome="UP",
            size=10.0,
            discount_percent=10.0,
        )

        assert order.price == pytest.approx(0.549)
        assert order.fill_price == pytest.approx(0.549)
        assert order.shares_bought == pytest.approx(10.0 / 0.549)
        assert order.max_profit == pytest.approx((10.0 / 0.549) - 10.0)
    
    @pytest.mark.asyncio
    async def test_place_order_has_uuid(self, connector):
        """Test that order has a valid UUID."""
        order = await connector.place_order(
            outcome="UP",
            size=10.0,
        )
        
        # UUID format: 8-4-4-4-12 hex characters
        import uuid
        try:
            uuid.UUID(order.order_id)
            valid_uuid = True
        except ValueError:
            valid_uuid = False
        
        assert valid_uuid


class TestPolymarketOrderCancellation:
    """Tests for order cancellation functionality."""
    
    @pytest.fixture
    def connector(self):
        """Create a connector in dry run mode."""
        return PolymarketConnector(
            private_key="0" * 64,
            dry_run=True,
        )
    
    @pytest.mark.asyncio
    async def test_cancel_existing_order(self, connector):
        """Test cancelling an existing order."""
        # Place an order first
        order = await connector.place_order(
            outcome="UP",
            size=10.0,
        )
        
        # Cancel it
        result = await connector.cancel_order(order.order_id)
        
        # In dry run, order is already filled, but cancel should still work
        assert result is True
    
    @pytest.mark.asyncio
    async def test_cancel_nonexistent_order(self, connector):
        """Test cancelling a non-existent order."""
        result = await connector.cancel_order("nonexistent-order-id")
        assert result is False


class TestPolymarketSimulatedState:
    """Tests for simulated state management."""
    
    def test_set_simulated_price_valid(self):
        """Test setting valid simulated prices."""
        connector = PolymarketConnector(private_key="0" * 64)
        
        connector.set_simulated_price("UP", 0.75)
        connector.set_simulated_price("DOWN", 0.25)
        
        assert connector._simulated_prices["UP"] == 0.75
        assert connector._simulated_prices["DOWN"] == 0.25
    
    def test_set_simulated_price_clamped_high(self):
        """Test that high prices are clamped to 0.99."""
        connector = PolymarketConnector(private_key="0" * 64)
        
        connector.set_simulated_price("UP", 1.5)
        
        assert connector._simulated_prices["UP"] == 0.99
    
    def test_set_simulated_price_clamped_low(self):
        """Test that low prices are clamped to 0.01."""
        connector = PolymarketConnector(private_key="0" * 64)
        
        connector.set_simulated_price("DOWN", -0.5)
        
        assert connector._simulated_prices["DOWN"] == 0.01
    
    def test_set_simulated_price_invalid_outcome(self):
        """Test that invalid outcome is ignored."""
        connector = PolymarketConnector(private_key="0" * 64)
        
        connector.set_simulated_price("INVALID", 0.5)
        
        # Should not add new key
        assert "INVALID" not in connector._simulated_prices
    
    def test_set_simulated_balance_valid(self):
        """Test setting valid simulated balance."""
        connector = PolymarketConnector(private_key="0" * 64)
        
        connector.set_simulated_balance(500.0)
        
        assert connector._simulated_balance == 500.0
    
    def test_set_simulated_balance_negative_clamped(self):
        """Test that negative balance is clamped to 0."""
        connector = PolymarketConnector(private_key="0" * 64)
        
        connector.set_simulated_balance(-100.0)
        
        assert connector._simulated_balance == 0.0


class TestPolymarketApiHeaders:
    """Tests for API header generation."""
    
    def test_generate_api_headers(self):
        """Test that API headers are generated correctly."""
        connector = PolymarketConnector(
            private_key="0" * 64,
            api_key="my-api-key",
            api_secret="my-secret",
            passphrase="my-passphrase",
        )
        
        timestamp = 1234567890000
        headers = connector._generate_api_headers(timestamp)
        
        assert headers["POLY_API_KEY"] == "my-api-key"
        assert headers["POLY_TIMESTAMP"] == "1234567890000"
        assert headers["POLY_PASSPHRASE"] == "my-passphrase"
        assert "POLY_SIGNATURE" in headers
        assert headers["Content-Type"] == "application/json"


class TestPolymarketEIP712Signature:
    """Tests for EIP-712 signature generation."""
    
    def test_generate_eip712_signature(self):
        """Test that EIP-712 signature is generated."""
        connector = PolymarketConnector(
            private_key="0" * 64,
        )
        
        order_data = {
            "market_id": "test-market",
            "outcome": "UP",
            "side": "BUY",
            "size": "10.0",
            "price": "0.50",
        }
        
        signature = connector._generate_eip712_signature(order_data)
        
        # Signature should start with 0x
        assert signature.startswith("0x")
        # Signature should be hex string
        assert all(c in "0123456789abcdef" for c in signature[2:])


class TestPolymarketConnectorClose:
    """Tests for connector cleanup."""
    
    @pytest.mark.asyncio
    async def test_close(self):
        """Test that close method works without error."""
        connector = PolymarketConnector(private_key="0" * 64)
        
        # Should not raise
        await connector.close()
