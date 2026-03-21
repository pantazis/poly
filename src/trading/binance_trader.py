"""Binance Futures API interface for hedge positions.

This module provides the BinanceTrader class for interacting with
Binance Futures API to open and close hedge positions.
"""

import asyncio
import hashlib
import hmac
import logging
import time
import uuid
from urllib.parse import urlencode

import aiohttp

from .models import BinancePosition

logger = logging.getLogger(__name__)


class BinanceTrader:
    """Interfaces with Binance Futures API for hedge positions.
    
    Handles authentication, position management, and order execution
    for BTCUSDT perpetual futures on Binance.
    
    Attributes:
        api_key: Binance API key
        api_secret: Binance API secret for HMAC signing
        api_url: Binance Futures API endpoint
        dry_run: If True, simulate orders without API calls
    """
    
    def __init__(
        self,
        api_key: str,
        api_secret: str,
        api_url: str = "https://fapi.binance.com",
        dry_run: bool = True,
    ):
        """Initialize BinanceTrader.
        
        Args:
            api_key: Binance API key
            api_secret: Binance API secret for HMAC signing
            api_url: Binance Futures API endpoint
            dry_run: If True, simulate orders without API calls
        """
        self.api_key = api_key
        self.api_secret = api_secret
        self.api_url = api_url.rstrip("/")
        self.dry_run = dry_run
        
        # Track simulated positions for dry run mode
        self._simulated_positions: dict[str, BinancePosition] = {}
        self._simulated_price: float = 50000.0  # Default simulated price
        
        self._session: aiohttp.ClientSession | None = None
    
    def _generate_signature(self, query_string: str) -> str:
        """Generate HMAC SHA256 signature for API authentication.
        
        Args:
            query_string: The query string to sign
            
        Returns:
            Hex-encoded HMAC SHA256 signature
        """
        return hmac.new(
            self.api_secret.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
    
    def _get_timestamp(self) -> int:
        """Get current timestamp in milliseconds."""
        return int(time.time() * 1000)
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={"X-MBX-APIKEY": self.api_key}
            )
        return self._session
    
    async def _signed_request(
        self,
        method: str,
        endpoint: str,
        params: dict | None = None,
    ) -> dict:
        """Make a signed API request.
        
        Args:
            method: HTTP method (GET, POST, DELETE)
            endpoint: API endpoint path
            params: Query parameters
            
        Returns:
            JSON response as dict
            
        Raises:
            aiohttp.ClientError: On network errors
            ValueError: On API errors
        """
        session = await self._get_session()
        
        params = params or {}
        params["timestamp"] = self._get_timestamp()
        
        query_string = urlencode(params)
        signature = self._generate_signature(query_string)
        query_string += f"&signature={signature}"
        
        url = f"{self.api_url}{endpoint}?{query_string}"
        
        async with session.request(method, url) as response:
            data = await response.json()
            
            if response.status != 200:
                error_msg = data.get("msg", str(data))
                logger.error(f"Binance API error: {error_msg}")
                raise ValueError(f"Binance API error: {error_msg}")
            
            return data

    async def _public_request(self, endpoint: str, params: dict | None = None) -> dict:
        """Make a public (unsigned) API request.
        
        Args:
            endpoint: API endpoint path
            params: Query parameters
            
        Returns:
            JSON response as dict
        """
        session = await self._get_session()
        
        url = f"{self.api_url}{endpoint}"
        if params:
            url += f"?{urlencode(params)}"
        
        async with session.get(url) as response:
            data = await response.json()
            
            if response.status != 200:
                error_msg = data.get("msg", str(data))
                raise ValueError(f"Binance API error: {error_msg}")
            
            return data
    
    async def connect(self) -> bool:
        """Verify API connectivity and permissions.
        
        Returns:
            True if connection successful and API key has trading permissions
        """
        if self.dry_run:
            logger.info("[DRY RUN] Binance connection simulated successfully")
            return True
        
        try:
            # Test connectivity with account info endpoint
            result = await self._signed_request("GET", "/fapi/v2/account")
            
            # Check if we can trade
            can_trade = result.get("canTrade", False)
            if not can_trade:
                logger.error("Binance API key does not have trading permissions")
                return False
            
            logger.info("Binance API connection verified successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to connect to Binance API: {e}")
            return False
    
    async def get_available_margin(self) -> float:
        """Get available margin in USDT.
        
        Returns:
            Available USDT margin for trading
        """
        if self.dry_run:
            logger.info("[DRY RUN] Returning simulated margin: 1000.0 USDT")
            return 1000.0
        
        try:
            result = await self._signed_request("GET", "/fapi/v2/account")
            
            # Find USDT asset balance
            for asset in result.get("assets", []):
                if asset.get("asset") == "USDT":
                    available = float(asset.get("availableBalance", 0))
                    logger.info(f"Available USDT margin: {available}")
                    return available
            
            logger.warning("USDT asset not found in account")
            return 0.0
            
        except Exception as e:
            logger.error(f"Failed to get available margin: {e}")
            raise
    
    async def get_current_price(self, symbol: str = "BTCUSDT") -> float:
        """Get current mark price for a symbol.
        
        Args:
            symbol: Trading pair symbol (default: BTCUSDT)
            
        Returns:
            Current mark price
        """
        if self.dry_run:
            logger.info(f"[DRY RUN] Returning simulated price for {symbol}: {self._simulated_price}")
            return self._simulated_price
        
        try:
            result = await self._public_request(
                "/fapi/v1/premiumIndex",
                {"symbol": symbol}
            )
            
            price = float(result.get("markPrice", 0))
            logger.info(f"Current {symbol} mark price: {price}")
            return price
            
        except Exception as e:
            logger.error(f"Failed to get current price for {symbol}: {e}")
            raise
    
    async def set_leverage(self, symbol: str, leverage: int) -> bool:
        """Set leverage for a symbol.
        
        Args:
            symbol: Trading pair symbol
            leverage: Leverage multiplier (1-125)
            
        Returns:
            True if successful
        """
        if self.dry_run:
            logger.info(f"[DRY RUN] Set leverage for {symbol} to {leverage}x")
            return True
        
        try:
            await self._signed_request(
                "POST",
                "/fapi/v1/leverage",
                {"symbol": symbol, "leverage": leverage}
            )
            
            logger.info(f"Set leverage for {symbol} to {leverage}x")
            return True
            
        except Exception as e:
            logger.error(f"Failed to set leverage for {symbol}: {e}")
            return False

    async def set_margin_mode(self, symbol: str, mode: str = "isolated") -> bool:
        """Set margin mode for a symbol.
        
        Args:
            symbol: Trading pair symbol
            mode: Margin mode ("isolated" or "crossed")
            
        Returns:
            True if successful
        """
        if self.dry_run:
            logger.info(f"[DRY RUN] Set margin mode for {symbol} to {mode}")
            return True
        
        try:
            margin_type = "ISOLATED" if mode.lower() == "isolated" else "CROSSED"
            
            await self._signed_request(
                "POST",
                "/fapi/v1/marginType",
                {"symbol": symbol, "marginType": margin_type}
            )
            
            logger.info(f"Set margin mode for {symbol} to {mode}")
            return True
            
        except ValueError as e:
            # Binance returns error if margin mode is already set
            if "No need to change margin type" in str(e):
                logger.info(f"Margin mode for {symbol} already set to {mode}")
                return True
            logger.error(f"Failed to set margin mode for {symbol}: {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to set margin mode for {symbol}: {e}")
            return False
    
    async def open_position(
        self,
        side: str,
        size_usd: float,
        leverage: int = 3,
        max_retries: int = 3,
    ) -> BinancePosition:
        """Open hedge position with market order.
        
        Args:
            side: "LONG" or "SHORT"
            size_usd: USD value of position
            leverage: Leverage multiplier
            max_retries: Number of retry attempts on failure
            
        Returns:
            BinancePosition with entry details
            
        Raises:
            ValueError: If all retries fail
        """
        symbol = "BTCUSDT"
        
        # Get current price for position size calculation
        current_price = await self.get_current_price(symbol)
        
        # Calculate position size: (size_usd / current_price) * leverage
        position_size = (size_usd / current_price) * leverage
        
        # Round to 3 decimal places (Binance precision for BTC)
        position_size = round(position_size, 3)
        
        if self.dry_run:
            position_id = str(uuid.uuid4())
            
            position = BinancePosition(
                position_id=position_id,
                symbol=symbol,
                side=side,
                size=position_size,
                leverage=leverage,
                entry_price=current_price,
                margin_mode="isolated",
                status="open",
                pnl=None,
            )
            
            self._simulated_positions[position_id] = position
            
            logger.info(
                f"[DRY RUN] Opened {side} position: "
                f"size={position_size} BTC, leverage={leverage}x, "
                f"entry_price={current_price}"
            )
            
            return position
        
        # Set up position parameters
        await self.set_leverage(symbol, leverage)
        await self.set_margin_mode(symbol, "isolated")
        
        # Determine order side for Binance
        order_side = "BUY" if side == "LONG" else "SELL"
        
        last_error: Exception | None = None
        
        for attempt in range(max_retries):
            try:
                result = await self._signed_request(
                    "POST",
                    "/fapi/v1/order",
                    {
                        "symbol": symbol,
                        "side": order_side,
                        "type": "MARKET",
                        "quantity": position_size,
                    }
                )
                
                # Extract fill price from response
                avg_price = float(result.get("avgPrice", current_price))
                order_id = str(result.get("orderId", uuid.uuid4()))
                
                position = BinancePosition(
                    position_id=order_id,
                    symbol=symbol,
                    side=side,
                    size=position_size,
                    leverage=leverage,
                    entry_price=avg_price,
                    margin_mode="isolated",
                    status="open",
                    pnl=None,
                )
                
                logger.info(
                    f"Opened {side} position: "
                    f"size={position_size} BTC, leverage={leverage}x, "
                    f"entry_price={avg_price}"
                )
                
                return position
                
            except Exception as e:
                last_error = e
                logger.warning(
                    f"Failed to open position (attempt {attempt + 1}/{max_retries}): {e}"
                )
                
                if attempt < max_retries - 1:
                    await asyncio.sleep(1)  # 1-second delay between retries
        
        # All retries failed
        error_msg = f"Failed to open position after {max_retries} attempts: {last_error}"
        logger.error(error_msg)
        raise ValueError(error_msg)

    async def close_position(self, position_id: str) -> BinancePosition:
        """Close position with market order.
        
        Args:
            position_id: Position identifier to close
            
        Returns:
            BinancePosition with PnL
            
        Raises:
            ValueError: If position not found or close fails
        """
        if self.dry_run:
            if position_id not in self._simulated_positions:
                raise ValueError(f"Position {position_id} not found")
            
            position = self._simulated_positions[position_id]
            
            # Simulate price movement for PnL calculation
            # Use a small random-ish movement based on position_id hash
            price_change_pct = (hash(position_id) % 100 - 50) / 1000  # -5% to +5%
            exit_price = position.entry_price * (1 + price_change_pct)
            
            # Calculate PnL
            if position.side == "LONG":
                pnl = (exit_price - position.entry_price) * position.size
            else:  # SHORT
                pnl = (position.entry_price - exit_price) * position.size
            
            closed_position = BinancePosition(
                position_id=position.position_id,
                symbol=position.symbol,
                side=position.side,
                size=position.size,
                leverage=position.leverage,
                entry_price=position.entry_price,
                margin_mode=position.margin_mode,
                status="closed",
                pnl=round(pnl, 2),
            )
            
            del self._simulated_positions[position_id]
            
            logger.info(
                f"[DRY RUN] Closed {position.side} position: "
                f"exit_price={exit_price:.2f}, pnl={pnl:.2f}"
            )
            
            return closed_position
        
        # For live trading, we need to close by placing opposite order
        # First, get current position info
        try:
            positions = await self._signed_request(
                "GET",
                "/fapi/v2/positionRisk",
                {"symbol": "BTCUSDT"}
            )
            
            # Find the position
            position_info = None
            for pos in positions:
                if float(pos.get("positionAmt", 0)) != 0:
                    position_info = pos
                    break
            
            if not position_info:
                raise ValueError(f"No open position found for {position_id}")
            
            position_amt = float(position_info.get("positionAmt", 0))
            entry_price = float(position_info.get("entryPrice", 0))
            leverage = int(position_info.get("leverage", 3))
            
            # Determine side and close direction
            if position_amt > 0:
                side = "LONG"
                close_side = "SELL"
                close_qty = abs(position_amt)
            else:
                side = "SHORT"
                close_side = "BUY"
                close_qty = abs(position_amt)
            
            # Place closing order
            result = await self._signed_request(
                "POST",
                "/fapi/v1/order",
                {
                    "symbol": "BTCUSDT",
                    "side": close_side,
                    "type": "MARKET",
                    "quantity": close_qty,
                    "reduceOnly": "true",
                }
            )
            
            exit_price = float(result.get("avgPrice", 0))
            
            # Calculate PnL
            if side == "LONG":
                pnl = (exit_price - entry_price) * close_qty
            else:
                pnl = (entry_price - exit_price) * close_qty
            
            closed_position = BinancePosition(
                position_id=position_id,
                symbol="BTCUSDT",
                side=side,
                size=close_qty,
                leverage=leverage,
                entry_price=entry_price,
                margin_mode="isolated",
                status="closed",
                pnl=round(pnl, 2),
            )
            
            logger.info(
                f"Closed {side} position: "
                f"exit_price={exit_price:.2f}, pnl={pnl:.2f}"
            )
            
            return closed_position
            
        except Exception as e:
            logger.error(f"Failed to close position {position_id}: {e}")
            raise
    
    async def close(self) -> None:
        """Close the aiohttp session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
