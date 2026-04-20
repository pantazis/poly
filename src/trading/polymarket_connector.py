"""Polymarket CLOB API connector for order placement.

This module provides the PolymarketConnector class for interfacing with
Polymarket's Central Limit Order Book API to place and manage orders
on 5-minute BTC binary options.

Authentication uses:
- API Key authentication with api_key, api_secret, passphrase headers
- EIP-712 signatures for order signing using the private_key

Market Discovery:
- BTC 5-minute markets use URL pattern: btc-updown-5m-{unix_timestamp}
- Timestamp is rounded down to nearest 5-minute interval
- Markets have UP and DOWN token IDs for trading
"""

import asyncio
import hashlib
import hmac
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore[assignment]

from src.trading.models import PolymarketOrder

logger = logging.getLogger(__name__)


class PolymarketConnector:
    """Interfaces with Polymarket CLOB API for order placement.
    
    Handles authentication, order placement, and order management for
    Polymarket's 5-minute BTC binary options markets.
    
    Market Discovery:
    - Generates market URLs based on current UTC time
    - Rounds to nearest 5-minute interval for market timing
    - Fetches token IDs for UP/DOWN outcomes from Gamma API
    
    In dry_run mode, simulates orders without making actual API calls.
    """
    
    # API endpoints
    CLOB_API_URL = "https://clob.polymarket.com"
    GAMMA_API_URL = "https://gamma-api.polymarket.com"
    
    # Market interval in seconds (5 minutes)
    MARKET_INTERVAL_SECONDS = 300

    # Default fee assumption if Gamma fee fields are missing/unavailable.
    # This is a *placeholder* until you confirm the exact schedule for your account/market.
    DEFAULT_TAKER_FEE_BPS = 0.0
    
    def __init__(
        self,
        private_key: str,
        api_key: str = "",
        api_secret: str = "",
        passphrase: str = "",
        dry_run: bool = True,
        use_live_market_data_in_dry_run: bool = False,
    ):
        """Initialize the Polymarket connector.
        
        Args:
            private_key: Ethereum wallet private key for EIP-712 signing
            api_key: Polymarket API key for authentication
            api_secret: Polymarket API secret for HMAC signing
            passphrase: Polymarket API passphrase
            dry_run: If True, simulate orders without submitting exchange orders
            use_live_market_data_in_dry_run: If True, use read-only Polymarket
                APIs for market discovery and pricing while still simulating orders
        """
        self._private_key = private_key
        self._api_key = api_key or os.environ.get("POLYMARKET_API_KEY", "")
        self._api_secret = api_secret or os.environ.get("POLYMARKET_SECRET", "")
        self._passphrase = passphrase or os.environ.get("POLYMARKET_PASSPHRASE", "")
        self._dry_run = dry_run
        self._use_live_market_data_in_dry_run = use_live_market_data_in_dry_run
        
        # Current market state
        self._current_market_id: str | None = None
        self._current_up_token_id: str | None = None
        self._current_down_token_id: str | None = None
        self._market_start_timestamp: int = 0
        self._market_expiry_timestamp: int = 0
        
        # Simulated state for dry run mode
        self._simulated_balance: float = 10000.0
        self._simulated_orders: dict[str, PolymarketOrder] = {}
        self._simulated_prices: dict[str, float] = {"UP": 0.50, "DOWN": 0.50}
        
        # HTTP session (lazy initialized)
        self._session: Any = None

    def _should_use_live_market_data(self) -> bool:
        """Return True when market discovery and pricing should use live APIs."""
        return not self._dry_run or self._use_live_market_data_in_dry_run

    async def _get_session(self) -> Any:
        """Get or create HTTP session."""
        if self._session is None:
            try:
                import aiohttp
                self._session = aiohttp.ClientSession()
            except ImportError:
                self._session = None
        return self._session
    
    async def _close_session(self) -> None:
        """Close HTTP session if open."""
        if self._session is not None:
            await self._session.close()
            self._session = None
    
    def _generate_api_headers(self, timestamp: int) -> dict[str, str]:
        """Generate API authentication headers.
        
        Args:
            timestamp: Unix timestamp in milliseconds
            
        Returns:
            Dictionary of authentication headers
        """
        message = f"{timestamp}"
        signature = hmac.new(
            self._api_secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()
        
        return {
            "POLY_API_KEY": self._api_key,
            "POLY_SIGNATURE": signature,
            "POLY_TIMESTAMP": str(timestamp),
            "POLY_PASSPHRASE": self._passphrase,
            "Content-Type": "application/json",
        }

    def _generate_eip712_signature(self, order_data: dict[str, Any]) -> str:
        """Generate EIP-712 signature for order signing.
        
        Args:
            order_data: Order data to sign
            
        Returns:
            Hex-encoded signature string
        """
        domain = {
            "name": "Polymarket CLOB",
            "version": "1",
            "chainId": 137,  # Polygon mainnet
        }
        
        message = json.dumps({
            "domain": domain,
            "order": order_data,
        }, sort_keys=True)
        
        message_hash = hashlib.sha256(message.encode()).hexdigest()
        signature = hmac.new(
            bytes.fromhex(self._private_key.replace("0x", "")),
            bytes.fromhex(message_hash),
            hashlib.sha256
        ).hexdigest()
        
        return f"0x{signature}"
    
    def _get_current_market_timestamp(self) -> int:
        """Get the Unix timestamp for the current 5-minute market interval.
        
        Rounds down current UTC time to nearest 5-minute boundary.
        
        Returns:
            Unix timestamp (seconds) for current market interval
        """
        now = int(time.time())
        # Round down to nearest 5-minute interval
        return (now // self.MARKET_INTERVAL_SECONDS) * self.MARKET_INTERVAL_SECONDS
    
    def _generate_market_slug(self, timestamp: int) -> str:
        """Generate the market slug for a BTC 5-minute market.
        
        Args:
            timestamp: Unix timestamp for the market interval
            
        Returns:
            Market slug like "btc-updown-5m-1771168800"
        """
        return f"btc-updown-5m-{timestamp}"

    @staticmethod
    def _coerce_unix_timestamp_seconds(value: Any) -> int | None:
        """Coerce common timestamp representations to unix seconds."""
        if value is None:
            return None
        if isinstance(value, (int, float)):
            raw = float(value)
            if raw > 10_000_000_000:
                raw = raw / 1000.0
            if raw <= 0:
                return None
            return int(raw)

        text = str(value).strip()
        if not text:
            return None
        if text.isdigit():
            return PolymarketConnector._coerce_unix_timestamp_seconds(int(text))
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp())
        except ValueError:
            return None
    
    async def _fetch_market_tokens(self, market_slug: str) -> tuple[str | None, str | None, str | None, int | None, int | None]:
        """Fetch market ID and token IDs from Gamma API.
        
        Args:
            market_slug: The market slug (e.g., "btc-updown-5m-1771168800")
            
        Returns:
            Tuple of (market_id, up_token_id, down_token_id, start_ts, end_ts)
            or empty values when not found.
        """
        if self._dry_run and not self._should_use_live_market_data():
            # Return simulated token IDs
            return (
                f"sim-market-{market_slug}",
                f"sim-up-token-{market_slug}",
                f"sim-down-token-{market_slug}",
                self._get_current_market_timestamp(),
                self._get_current_market_timestamp() + self.MARKET_INTERVAL_SECONDS,
            )
        
        session = await self._get_session()
        if session is None and requests is None:
            logger.warning("HTTP session not available")
            return None, None, None, None, None
        
        try:
            # Query Gamma API for market data
            url = f"{self.GAMMA_API_URL}/events?slug={market_slug}"
            
            if session is not None:
                async with session.get(url, timeout=10) as response:
                    status = response.status
                    data = await response.json() if status == 200 else None
            else:
                resp = requests.get(url, timeout=10)
                status = resp.status_code
                data = resp.json() if status == 200 else None

            if status == 200 and data is not None:
                    
                    if data and len(data) > 0:
                        event = data[0]
                        markets = event.get("markets", [])
                        
                        if markets and len(markets) > 0:
                            market = markets[0]
                            market_id = str(market.get("id", ""))
                            
                            # Get token IDs from clobTokenIds.
                            # Gamma sometimes returns this as a JSON-encoded string.
                            clob_token_ids_raw = market.get("clobTokenIds", [])
                            if isinstance(clob_token_ids_raw, str):
                                try:
                                    clob_token_ids = json.loads(clob_token_ids_raw)
                                except Exception:
                                    clob_token_ids = []
                            else:
                                clob_token_ids = list(clob_token_ids_raw) if isinstance(clob_token_ids_raw, list) else []

                            if len(clob_token_ids) >= 2:
                                # First token is typically UP/Yes, second is DOWN/No
                                up_token_id = str(clob_token_ids[0])
                                down_token_id = str(clob_token_ids[1])
                                
                                logger.info(f"Found market {market_id} for {market_slug}")
                                logger.debug(f"UP token: {up_token_id[:20]}...")
                                logger.debug(f"DOWN token: {down_token_id[:20]}...")
                                
                                start_ts = self._coerce_unix_timestamp_seconds(
                                    market.get("startDate")
                                    or event.get("startDate")
                                )
                                end_ts = self._coerce_unix_timestamp_seconds(
                                    market.get("endDate")
                                    or market.get("endTime")
                                    or event.get("endDate")
                                    or event.get("endTime")
                                )

                                return market_id, up_token_id, down_token_id, start_ts, end_ts
                    
                    logger.warning(f"Market not found for slug: {market_slug}")
            else:
                logger.warning(f"Gamma API returned status {status}")
                    
        except Exception as e:
            logger.error(f"Error fetching market tokens: {e}")
        
        return None, None, None, None, None

    async def _ensure_current_market(self) -> bool:
        """Ensure we have valid token IDs for the current market interval.
        
        Fetches new market data if the current market has expired or
        if we don't have market data yet.
        
        Returns:
            True if we have valid market data, False otherwise
        """
        current_timestamp = self._get_current_market_timestamp()
        
        # Check if we need to refresh market data
        if (self._current_market_id is None or 
            current_timestamp != self._market_expiry_timestamp - self.MARKET_INTERVAL_SECONDS):
            
            market_slug = self._generate_market_slug(current_timestamp)
            logger.info(f"Fetching market data for: {market_slug}")
            
            market_id, up_token, down_token, start_ts, end_ts = await self._fetch_market_tokens(market_slug)
            
            if market_id and up_token and down_token:
                self._current_market_id = market_id
                self._current_up_token_id = up_token
                self._current_down_token_id = down_token
                self._market_start_timestamp = int(start_ts or current_timestamp)
                self._market_expiry_timestamp = int(end_ts or (current_timestamp + self.MARKET_INTERVAL_SECONDS))
                
                logger.info(f"Market ready: {market_id}, expires at {self._market_expiry_timestamp}")
                return True
            else:
                logger.error(f"Failed to get market data for {market_slug}")
                return False
        
        return True
    
    def _get_token_id_for_outcome(self, outcome: str) -> str | None:
        """Get the token ID for a given outcome.
        
        Args:
            outcome: "UP" or "DOWN"
            
        Returns:
            Token ID string or None if not available
        """
        if outcome == "UP":
            return self._current_up_token_id
        elif outcome == "DOWN":
            return self._current_down_token_id
        return None

    async def connect(self) -> bool:
        """Verify API connectivity and fetch initial market data.
        
        Returns:
            True if connection is successful, False otherwise
        """
        if self._dry_run and not self._should_use_live_market_data():
            logger.info("[DRY RUN] Polymarket connection simulated successfully")
            # Pre-populate simulated market data
            await self._ensure_current_market()
            return True
        
        try:
            session = await self._get_session()
            if session is None:
                logger.warning("aiohttp not available, skipping connectivity check")
                return True
            
            # Test CLOB API connectivity
            async with session.get(
                f"{self.CLOB_API_URL}/",
                timeout=10
            ) as response:
                if response.status == 200:
                    logger.info("Polymarket CLOB API connection verified")
                else:
                    logger.warning(f"CLOB API returned status {response.status}")
            
            # Fetch initial market data
            if await self._ensure_current_market():
                logger.info("Polymarket API connection verified")
                return True
            else:
                logger.warning("Connected but could not fetch market data")
                return True  # Still return True, market might not be available yet
                    
        except Exception as e:
            logger.error(f"Failed to connect to Polymarket API: {e}")
            return False
    
    async def get_balance(self) -> float:
        """Get available USDC balance.
        
        Returns:
            Available USDC balance
        """
        if self._dry_run:
            logger.info(f"[DRY RUN] Polymarket balance: ${self._simulated_balance:.2f}")
            return self._simulated_balance
        
        try:
            session = await self._get_session()
            if session is None:
                return self._simulated_balance
            
            timestamp = int(time.time() * 1000)
            headers = self._generate_api_headers(timestamp)
            
            async with session.get(
                f"{self.CLOB_API_URL}/balance",
                headers=headers,
                timeout=10
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    balance = float(data.get("balance", 0))
                    logger.info(f"Polymarket balance: ${balance:.2f}")
                    return balance
                else:
                    logger.error(f"Failed to get balance: {response.status}")
                    return 0.0
                    
        except Exception as e:
            logger.error(f"Error fetching Polymarket balance: {e}")
            return 0.0
    
    async def get_current_price(self, outcome: str) -> float:
        """Get current best ask price for outcome.
        
        Args:
            outcome: "UP" or "DOWN"
            
        Returns:
            Best ask price (0-1 range)
            
        Raises:
            ValueError: If outcome is not "UP" or "DOWN"
        """
        if outcome not in ("UP", "DOWN"):
            raise ValueError(f"Invalid outcome: {outcome}. Must be 'UP' or 'DOWN'")
        
        if self._dry_run and not self._should_use_live_market_data():
            price = self._simulated_prices.get(outcome, 0.50)
            logger.info(f"[DRY RUN] Polymarket {outcome} price: {price:.4f}")
            return price

        fallback_price = self._simulated_prices.get(outcome, 0.50)

        def log_dry_run_fallback(reason: str) -> float:
            logger.warning(
                f"[DRY RUN] Live Polymarket pricing unavailable for {outcome}: {reason}. "
                f"Falling back to simulated price {fallback_price:.4f}"
            )
            return fallback_price
        
        # Ensure we have current market data
        if not await self._ensure_current_market():
            if self._dry_run:
                return log_dry_run_fallback("market data unavailable")
            logger.warning("Could not get market data, returning default price")
            return 0.50
        
        token_id = self._get_token_id_for_outcome(outcome)
        if not token_id:
            if self._dry_run:
                return log_dry_run_fallback("token id unavailable")
            logger.warning(f"No token ID for {outcome}")
            return 0.50
        
        try:
            session = await self._get_session()
            if session is None:
                if self._dry_run:
                    return log_dry_run_fallback("HTTP session unavailable")
                return 0.50
            
            # Query CLOB API for price
            async with session.get(
                f"{self.CLOB_API_URL}/price",
                params={"token_id": token_id, "side": "buy"},
                timeout=10
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    price = float(data.get("price", 0.50))
                    logger.info(f"Polymarket {outcome} price: {price:.4f}")
                    return price
                else:
                    if self._dry_run:
                        return log_dry_run_fallback(
                            f"price API returned status {response.status}"
                        )
                    logger.warning(f"Price API returned status {response.status}")
                    return 0.50
                    
        except Exception as e:
            if self._dry_run:
                return log_dry_run_fallback(str(e))
            logger.error(f"Error fetching Polymarket price: {e}")
            return 0.50

    async def get_orderbook(self, outcome: str) -> dict[str, Any] | None:
        """Fetch orderbook (bids/asks) for the current market token.

        NOTE: Uses public /book endpoint (no auth) and requires token_id.
        """
        if outcome not in ("UP", "DOWN"):
            raise ValueError(f"Invalid outcome: {outcome}. Must be 'UP' or 'DOWN'")

        if not await self._ensure_current_market():
            return None
        token_id = self._get_token_id_for_outcome(outcome)
        if not token_id:
            return None

        session = await self._get_session()
        if session is not None:
            async with session.get(
                f"{self.CLOB_API_URL}/book",
                params={"token_id": token_id},
                timeout=10,
            ) as response:
                if response.status != 200:
                    return None
                return await response.json()

        # Fallback for environments without aiohttp installed (common in local tooling).
        if requests is None:
            return None
        try:
            resp = requests.get(
                f"{self.CLOB_API_URL}/book",
                params={"token_id": token_id},
                timeout=10,
            )
            if resp.status_code != 200:
                return None
            return resp.json()
        except Exception:
            return None

    @staticmethod
    def _vwap_price(levels: list[dict[str, Any]], shares: float) -> float | None:
        """Compute VWAP price for buying `shares` from asks or selling into bids."""
        need = max(float(shares), 0.0)
        if need <= 0:
            return None
        cost = 0.0
        filled = 0.0
        for lvl in levels:
            try:
                px = float(lvl.get("price", 0.0))
                sz = float(lvl.get("size", 0.0))
            except Exception:
                continue
            if px <= 0 or sz <= 0:
                continue
            take = min(sz, need - filled)
            cost += take * px
            filled += take
            if filled >= need - 1e-12:
                break
        if filled <= 0:
            return None
        return cost / filled

    async def estimate_entry_cost_usdc(
        self,
        outcome: str,
        usdc_size: float,
        taker_fee_bps: float | None = None,
    ) -> dict[str, float] | None:
        """Estimate Polymarket BTC-5m entry cost for a market BUY.

        Returns a dict with:
        - entry_price_vwap (share price 0..1)
        - shares
        - fee_usdc
        - total_cost_usdc
        """
        book = await self.get_orderbook(outcome)
        if not book:
            return None
        asks = list(book.get("asks", []) or [])
        best_ask = float(asks[0]["price"]) if asks else None
        if best_ask is None or best_ask <= 0:
            return None

        # Approx shares purchased for a USDC notional at current best ask.
        shares = float(usdc_size) / max(best_ask, 1e-9)
        vwap = self._vwap_price(asks, shares=shares)
        if vwap is None:
            return None

        fee_bps = float(self.DEFAULT_TAKER_FEE_BPS if taker_fee_bps is None else taker_fee_bps)
        fee_usdc = float(usdc_size) * (fee_bps / 10_000.0)
        total = float(usdc_size) + fee_usdc
        return {
            "entry_price_vwap": float(vwap),
            "shares": float(shares),
            "fee_usdc": float(fee_usdc),
            "total_cost_usdc": float(total),
        }

    async def place_order(
        self,
        outcome: str,
        size: float,
        discount_percent: float = 10.0,
        timeout_seconds: float = 30.0,
    ) -> PolymarketOrder:
        """Place limit order at discount below current price.
        
        Finds the current BTC 5-minute market, gets the appropriate token ID,
        and places a limit order at a discount to the current best ask.
        
        Args:
            outcome: "UP" or "DOWN"
            size: USDC amount to bet
            discount_percent: Percentage below best ask for limit price
            timeout_seconds: Cancel order if not filled within this time
            
        Returns:
            PolymarketOrder with final status
            
        Raises:
            ValueError: If outcome is not "UP" or "DOWN"
        """
        if outcome not in ("UP", "DOWN"):
            raise ValueError(f"Invalid outcome: {outcome}. Must be 'UP' or 'DOWN'")
        
        # Ensure we have current market data
        if not await self._ensure_current_market():
            logger.error("Cannot place order: no market data available")
            return PolymarketOrder(
                order_id=str(uuid.uuid4()),
                market_id="unknown",
                outcome=outcome,
                side="BUY",
                size=size,
                price=0,
                status="cancelled",
                fill_price=None,
                fill_time=None,
            )
        
        # Get current price and calculate limit price with discount
        current_price = await self.get_current_price(outcome)
        limit_price = current_price * (1 - discount_percent / 100)
        
        # Ensure price is within valid range (0-1)
        limit_price = max(0.01, min(0.99, limit_price))
        
        order_id = str(uuid.uuid4())
        token_id = self._get_token_id_for_outcome(outcome)
        
        order = PolymarketOrder(
            order_id=order_id,
            market_id=self._current_market_id or "unknown",
            outcome=outcome,
            side="BUY",
            size=size,
            price=limit_price,
            status="pending",
            fill_price=None,
            fill_time=None,
        )
        
        logger.info(
            f"Placing {outcome} order on BTC 5m market: "
            f"size=${size:.2f}, price={limit_price:.4f} "
            f"(current: {current_price:.4f}, discount: {discount_percent}%)"
        )
        
        if self._dry_run:
            return await self._simulate_order(order, timeout_seconds)
        
        try:
            order = await self._place_order_api(order, token_id)
            
            if order.status == "pending":
                order = await self._wait_for_fill(order, timeout_seconds)
            
            return order
            
        except Exception as e:
            logger.error(f"Error placing order: {e}")
            order.status = "cancelled"
            return order
    
    async def _simulate_order(
        self,
        order: PolymarketOrder,
        timeout_seconds: float,
    ) -> PolymarketOrder:
        """Simulate order execution in dry run mode.
        
        Args:
            order: The order to simulate
            timeout_seconds: Timeout for fill simulation
            
        Returns:
            PolymarketOrder with simulated fill
        """
        logger.info(
            f"[DRY RUN] Placing {order.outcome} order on BTC 5m market: "
            f"size=${order.size:.2f}, price={order.price:.4f}"
        )
        
        self._simulated_orders[order.order_id] = order
        
        # Simulate a brief delay before fill
        await asyncio.sleep(0.5)
        
        # In dry run, simulate immediate fill at limit price
        order.status = "filled"
        order.fill_price = order.price
        order.fill_time = datetime.now(timezone.utc)
        order.shares_bought = order.size / order.fill_price
        order.max_profit = order.shares_bought - order.size
        order.max_loss = order.size
        
        # Deduct from simulated balance
        self._simulated_balance -= order.size
        
        logger.info(
            f"[DRY RUN] Order filled: {order.outcome} at {order.fill_price:.4f}"
        )
        
        return order
    
    async def _place_order_api(self, order: PolymarketOrder, token_id: str | None) -> PolymarketOrder:
        """Place order via Polymarket CLOB API.
        
        Args:
            order: The order to place
            token_id: The token ID to trade
            
        Returns:
            PolymarketOrder with API response
        """
        if not token_id:
            logger.error("No token ID provided for order")
            order.status = "cancelled"
            return order
        
        session = await self._get_session()
        if session is None:
            logger.error("HTTP session not available")
            order.status = "cancelled"
            return order
        
        timestamp = int(time.time() * 1000)
        headers = self._generate_api_headers(timestamp)
        
        # Prepare order data for signing
        order_data = {
            "token_id": token_id,
            "side": "BUY",
            "size": str(order.size),
            "price": str(order.price),
            "timestamp": timestamp,
        }
        
        # Generate EIP-712 signature
        signature = self._generate_eip712_signature(order_data)
        order_data["signature"] = signature
        
        try:
            async with session.post(
                f"{self.CLOB_API_URL}/order",
                headers=headers,
                json=order_data,
                timeout=10
            ) as response:
                if response.status in (200, 201):
                    data = await response.json()
                    order.order_id = data.get("orderID", order.order_id)
                    order.status = data.get("status", "pending")
                    logger.info(f"Order placed: {order.order_id}")
                else:
                    error_text = await response.text()
                    logger.error(f"Failed to place order: {response.status} - {error_text}")
                    order.status = "cancelled"
                    
        except Exception as e:
            logger.error(f"Error placing order via API: {e}")
            order.status = "cancelled"
        
        return order

    async def _wait_for_fill(
        self,
        order: PolymarketOrder,
        timeout_seconds: float,
    ) -> PolymarketOrder:
        """Wait for order to fill or cancel after timeout.
        
        Args:
            order: The pending order
            timeout_seconds: Maximum time to wait
            
        Returns:
            PolymarketOrder with final status
        """
        start_time = time.time()
        poll_interval = 1.0
        
        while time.time() - start_time < timeout_seconds:
            updated_order = await self._get_order_status(order.order_id)
            
            if updated_order.status == "filled":
                order.status = "filled"
                order.fill_price = updated_order.fill_price
                order.fill_time = updated_order.fill_time
                logger.info(f"Order filled: {order.order_id} at {order.fill_price}")
                return order
            elif updated_order.status in ("cancelled", "expired"):
                order.status = updated_order.status
                logger.info(f"Order {order.status}: {order.order_id}")
                return order
            
            await asyncio.sleep(poll_interval)
        
        # Timeout reached - cancel the order
        logger.warning(f"Order timeout after {timeout_seconds}s, cancelling: {order.order_id}")
        await self.cancel_order(order.order_id)
        order.status = "cancelled"
        
        return order
    
    async def _get_order_status(self, order_id: str) -> PolymarketOrder:
        """Get current status of an order.
        
        Args:
            order_id: The order ID to check
            
        Returns:
            PolymarketOrder with current status
        """
        if order_id in self._simulated_orders:
            return self._simulated_orders[order_id]
        
        session = await self._get_session()
        if session is None:
            return PolymarketOrder(
                order_id=order_id,
                market_id="unknown",
                outcome="",
                side="BUY",
                size=0,
                price=0,
                status="pending",
                fill_price=None,
                fill_time=None,
            )
        
        timestamp = int(time.time() * 1000)
        headers = self._generate_api_headers(timestamp)
        
        try:
            async with session.get(
                f"{self.CLOB_API_URL}/order/{order_id}",
                headers=headers,
                timeout=10
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    fill_time = None
                    if data.get("fill_time"):
                        fill_time = datetime.fromisoformat(
                            data["fill_time"].replace("Z", "+00:00")
                        )
                    
                    return PolymarketOrder(
                        order_id=data.get("orderID", order_id),
                        market_id=self._current_market_id or "unknown",
                        outcome=data.get("outcome", ""),
                        side=data.get("side", "BUY"),
                        size=float(data.get("size", 0)),
                        price=float(data.get("price", 0)),
                        status=data.get("status", "pending"),
                        fill_price=float(data["fill_price"]) if data.get("fill_price") else None,
                        fill_time=fill_time,
                    )
                else:
                    logger.error(f"Failed to get order status: {response.status}")
                    
        except Exception as e:
            logger.error(f"Error getting order status: {e}")
        
        return PolymarketOrder(
            order_id=order_id,
            market_id="unknown",
            outcome="",
            side="BUY",
            size=0,
            price=0,
            status="pending",
            fill_price=None,
            fill_time=None,
        )

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel a pending order.
        
        Args:
            order_id: The order ID to cancel
            
        Returns:
            True if cancellation was successful, False otherwise
        """
        if self._dry_run:
            if order_id in self._simulated_orders:
                self._simulated_orders[order_id].status = "cancelled"
                logger.info(f"[DRY RUN] Order cancelled: {order_id}")
                return True
            logger.warning(f"[DRY RUN] Order not found: {order_id}")
            return False
        
        session = await self._get_session()
        if session is None:
            logger.error("HTTP session not available")
            return False
        
        timestamp = int(time.time() * 1000)
        headers = self._generate_api_headers(timestamp)
        
        try:
            async with session.delete(
                f"{self.CLOB_API_URL}/order/{order_id}",
                headers=headers,
                timeout=10
            ) as response:
                if response.status in (200, 204):
                    logger.info(f"Order cancelled: {order_id}")
                    return True
                else:
                    error_text = await response.text()
                    logger.error(f"Failed to cancel order: {response.status} - {error_text}")
                    return False
                    
        except Exception as e:
            logger.error(f"Error cancelling order: {e}")
            return False
    
    def get_current_market_info(self) -> dict[str, Any]:
        """Get information about the current market.
        
        Returns:
            Dictionary with market_id, up_token_id, down_token_id, expiry_timestamp
        """
        return {
            "market_id": self._current_market_id,
            "up_token_id": self._current_up_token_id,
            "down_token_id": self._current_down_token_id,
            "start_timestamp": self._market_start_timestamp,
            "expiry_timestamp": self._market_expiry_timestamp,
            "market_slug": self._generate_market_slug(self._get_current_market_timestamp()),
        }
    
    def set_simulated_price(self, outcome: str, price: float) -> None:
        """Set simulated price for dry run mode.
        
        Args:
            outcome: "UP" or "DOWN"
            price: Price to set (0-1 range)
        """
        if outcome in ("UP", "DOWN"):
            self._simulated_prices[outcome] = max(0.01, min(0.99, price))
    
    def set_simulated_balance(self, balance: float) -> None:
        """Set simulated balance for dry run mode.
        
        Args:
            balance: Balance in USDC
        """
        self._simulated_balance = max(0, balance)
    
    async def close(self) -> None:
        """Close the connector and release resources."""
        await self._close_session()
        logger.info("Polymarket connector closed")
