"""LiquidationCollector - Main orchestrator that coordinates all components."""

import asyncio
import logging
import signal
from typing import Any

from .aggregator import TimeAggregator
from .connector import BinanceConnector
from .datastore import DataStore
from .filter import EventFilter
from .health import HealthMonitor
from .models import CollectorConfig, HealthMetrics, WindowAggregation
from .normalizer import DataNormalizer

logger = logging.getLogger(__name__)


class LiquidationCollector:
    """Main orchestrator that coordinates all components."""
    
    def __init__(self, config: CollectorConfig):
        self._config = config
        self._running = False
        self._shutdown_event = asyncio.Event()
        
        # Initialize components
        self._connector = BinanceConnector(on_event=self._handle_event)
        self._filter = EventFilter(threshold_usd=config.significance_threshold_usd)
        self._data_store = DataStore(data_dir=config.data_dir)
        self._aggregator = TimeAggregator()
        self._health_monitor = HealthMonitor(connector=self._connector)
    
    async def _handle_event(self, raw: dict[str, Any]) -> None:
        """Process incoming liquidation event through the pipeline."""
        try:
            # Normalize
            event = DataNormalizer.normalize_binance(raw)
            
            # Classify
            event = self._filter.classify(event)
            
            # Store
            await self._data_store.write(event)
            
            # Aggregate
            self._aggregator.add_event(event)
            
            # Record metrics
            self._health_monitor.record_event(event)
            
            # Log significant events
            if event.is_significant:
                logger.info(
                    f"LIQUIDATION: {event.symbol} {event.side} "
                    f"${event.usd_size:,.0f} @ {event.price:,.2f}"
                )
        except Exception as e:
            logger.error(f"Error processing event: {e}")
    
    async def _periodic_flush(self) -> None:
        """Periodically flush data to disk."""
        while self._running:
            await asyncio.sleep(self._config.flush_interval_seconds)
            try:
                await self._data_store.flush()
            except Exception as e:
                logger.error(f"Error flushing data: {e}")
    
    async def _periodic_health_check(self) -> None:
        """Periodically check system health."""
        while self._running:
            await asyncio.sleep(30)
            try:
                await self._health_monitor.check_health()
            except Exception as e:
                logger.error(f"Error checking health: {e}")
    
    async def start(self) -> None:
        """Start the collector. Blocks until shutdown signal."""
        self._running = True
        logger.info("Starting Liquidation Collector")
        logger.info(f"Data directory: {self._config.data_dir}")
        logger.info(f"Significance threshold: ${self._config.significance_threshold_usd:,.0f}")
        
        # Set up signal handlers (Unix only, skip on Windows)
        import sys
        if sys.platform != "win32":
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, lambda: asyncio.create_task(self.shutdown()))
        
        # Start background tasks
        flush_task = asyncio.create_task(self._periodic_flush())
        health_task = asyncio.create_task(self._periodic_health_check())
        connect_task = asyncio.create_task(self._connector.connect())
        
        # Wait for shutdown or KeyboardInterrupt
        try:
            await self._shutdown_event.wait()
        except asyncio.CancelledError:
            pass
        
        # Cancel background tasks
        flush_task.cancel()
        health_task.cancel()
        connect_task.cancel()
        
        try:
            await asyncio.gather(flush_task, health_task, connect_task, return_exceptions=True)
        except asyncio.CancelledError:
            pass
    
    async def shutdown(self) -> None:
        """Graceful shutdown within 10 seconds."""
        if not self._running:
            return
        
        logger.info("Shutting down...")
        self._running = False
        
        # Close WebSocket (5s timeout)
        try:
            await asyncio.wait_for(self._connector.disconnect(), timeout=5.0)
        except asyncio.TimeoutError:
            logger.warning("WebSocket close timed out")
        
        # Flush and close data store (4s timeout)
        try:
            await asyncio.wait_for(self._data_store.close(), timeout=4.0)
        except asyncio.TimeoutError:
            logger.error("Data flush timed out, some data may be lost")
        
        # Log final metrics
        metrics = self._health_monitor.get_metrics()
        logger.info(
            f"Final metrics: {metrics.events_received_total} events received, "
            f"{metrics.events_filtered_significant} significant"
        )
        
        self._shutdown_event.set()
    
    def get_aggregations(self) -> list[WindowAggregation]:
        """Returns current time-window aggregations."""
        return self._aggregator.get_aggregations()
    
    def get_health(self) -> HealthMetrics:
        """Returns current health metrics."""
        return self._health_monitor.get_metrics()
