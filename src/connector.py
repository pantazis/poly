"""BinanceConnector - WebSocket connection to Binance Futures liquidation stream."""

import asyncio
import json
import logging
import time
from typing import Any, Awaitable, Callable

import websockets
from websockets.client import WebSocketClientProtocol

logger = logging.getLogger(__name__)

BINANCE_WS_URL = "wss://fstream.binance.com/ws/!forceOrder@arr"
MAX_CONNECTION_HOURS = 23  # Reconnect before 24-hour limit


class BinanceConnector:
    """Connects to Binance forceOrder WebSocket stream."""
    
    def __init__(self, on_event: Callable[[dict[str, Any]], Awaitable[None]]):
        """
        Args:
            on_event: Async callback invoked for each forceOrder message
        """
        self._on_event = on_event
        self._ws: WebSocketClientProtocol | None = None
        self._running = False
        self._connected = False
        self._connect_time: float | None = None
        self._reconnect_attempt = 0
    
    @staticmethod
    def _get_backoff_delay(attempt: int) -> float:
        """Calculate exponential backoff delay: 1s, 2s, 4s, 8s, 16s, max 30s."""
        delay = min(2 ** (attempt - 1), 30) if attempt > 0 else 1
        return float(delay)
    
    async def connect(self) -> None:
        """Establish WebSocket connection. Handles reconnection internally."""
        self._running = True
        
        while self._running:
            try:
                await self._connect_and_listen()
            except websockets.ConnectionClosed as e:
                logger.warning(f"WebSocket connection closed: {e}")
            except Exception as e:
                logger.error(f"WebSocket error: {e}")
            
            if not self._running:
                break
            
            # Reconnect with backoff
            self._connected = False
            self._reconnect_attempt += 1
            delay = self._get_backoff_delay(self._reconnect_attempt)
            logger.info(f"Reconnecting in {delay}s (attempt {self._reconnect_attempt})")
            await asyncio.sleep(delay)
    
    async def _connect_and_listen(self) -> None:
        """Connect to WebSocket and process messages."""
        logger.info(f"Connecting to {BINANCE_WS_URL}")
        
        async with websockets.connect(BINANCE_WS_URL, ping_interval=30, ping_timeout=10) as ws:
            self._ws = ws
            self._connected = True
            self._connect_time = time.time()
            self._reconnect_attempt = 0
            logger.info("Connected to Binance WebSocket")
            
            # Schedule proactive reconnection before 24-hour limit
            reconnect_task = asyncio.create_task(self._schedule_reconnect())
            
            try:
                async for message in ws:
                    if not self._running:
                        break
                    
                    try:
                        data = json.loads(message)
                        if data.get("e") == "forceOrder":
                            await self._on_event(data)
                    except json.JSONDecodeError:
                        logger.warning(f"Invalid JSON received: {message[:100]}")
                    except Exception as e:
                        logger.error(f"Error processing message: {e}")
            finally:
                reconnect_task.cancel()
                try:
                    await reconnect_task
                except asyncio.CancelledError:
                    pass
    
    async def _schedule_reconnect(self) -> None:
        """Schedule reconnection before 24-hour limit."""
        await asyncio.sleep(MAX_CONNECTION_HOURS * 3600)
        if self._running and self._ws:
            logger.info("Proactive reconnection (approaching 24-hour limit)")
            await self._ws.close()
    
    async def disconnect(self) -> None:
        """Gracefully close WebSocket connection."""
        self._running = False
        if self._ws:
            await self._ws.close()
            self._ws = None
        self._connected = False
        logger.info("Disconnected from Binance WebSocket")
    
    @property
    def is_connected(self) -> bool:
        """Returns True if WebSocket is currently connected."""
        return self._connected
    
    @property
    def uptime_seconds(self) -> float:
        """Returns seconds since last successful connection."""
        if self._connect_time is None:
            return 0.0
        return time.time() - self._connect_time
