"""Trade logging component for the Liquidation Trading Bot.

This module provides CSV-based trade logging with daily file rotation,
buffered writes, and graceful shutdown support.
"""

import asyncio
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TextIO

from src.trading.models import EntrySignal, TradeLogEntry


class TradeLogger:
    """Records all trade activity to CSV files.
    
    Implements daily CSV file rotation with pattern `trades_YYYY-MM-DD.csv`,
    buffered writes with configurable flush intervals, and graceful shutdown.
    
    Attributes:
        log_dir: Directory for trade log CSV files
        flush_interval_seconds: Interval for flushing writes to disk
    """
    
    CSV_HEADERS = [
        "timestamp",
        "event_type", 
        "trade_id",
        "exchange",
        "side",
        "size",
        "price",
        "pnl",
        "is_dry_run",
        "details",
    ]
    
    def __init__(self, log_dir: Path, flush_interval_seconds: float = 5.0):
        """Initialize the TradeLogger.
        
        Args:
            log_dir: Directory for trade log CSV files
            flush_interval_seconds: Interval for flushing writes to disk
        """
        self.log_dir = log_dir
        self.flush_interval_seconds = flush_interval_seconds
        
        # Create log directory if it doesn't exist
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # Current file state
        self._current_date: str | None = None
        self._current_file: TextIO | None = None
        self._csv_writer: csv.writer | None = None
        
        # Buffer for pending writes
        self._buffer: list[TradeLogEntry] = []
        self._buffer_lock = asyncio.Lock()
        
        # Flush task
        self._flush_task: asyncio.Task | None = None
        self._running = False
    
    def _get_file_path(self, date_str: str) -> Path:
        """Get the CSV file path for a given date."""
        return self.log_dir / f"trades_{date_str}.csv"
    
    def _ensure_file_for_date(self, date_str: str) -> None:
        """Ensure the correct file is open for the given date.
        
        Handles daily file rotation by closing the old file and opening
        a new one when the date changes.
        """
        if self._current_date == date_str and self._current_file is not None:
            return
        
        # Close existing file if open
        if self._current_file is not None:
            self._current_file.close()
            self._current_file = None
            self._csv_writer = None
        
        # Open new file
        file_path = self._get_file_path(date_str)
        file_exists = file_path.exists()
        
        self._current_file = open(file_path, "a", newline="", encoding="utf-8")
        self._csv_writer = csv.writer(self._current_file)
        self._current_date = date_str
        
        # Write headers if new file
        if not file_exists:
            self._csv_writer.writerow(self.CSV_HEADERS)
    
    def _write_entry(self, entry: TradeLogEntry) -> None:
        """Write a single log entry to the CSV file."""
        date_str = entry.timestamp.strftime("%Y-%m-%d")
        self._ensure_file_for_date(date_str)
        
        if self._csv_writer is None:
            return
        
        row = [
            entry.timestamp.isoformat(),
            entry.event_type,
            entry.trade_id or "",
            entry.exchange or "",
            entry.side or "",
            str(entry.size) if entry.size is not None else "",
            str(entry.price) if entry.price is not None else "",
            str(entry.pnl) if entry.pnl is not None else "",
            str(entry.is_dry_run).lower(),
            entry.details or "",
        ]
        self._csv_writer.writerow(row)
    
    async def _start_flush_loop(self) -> None:
        """Background task that periodically flushes the buffer to disk."""
        self._running = True
        while self._running:
            await asyncio.sleep(self.flush_interval_seconds)
            await self.flush()
    
    def _start_flush_task(self) -> None:
        """Start the background flush task if not already running."""
        if self._flush_task is None or self._flush_task.done():
            self._flush_task = asyncio.create_task(self._start_flush_loop())
    
    async def log_signal(self, signal: EntrySignal, is_dry_run: bool) -> None:
        """Log entry signal detection.
        
        Args:
            signal: The entry signal that was detected
            is_dry_run: Whether this is a dry run trade
        """
        details = json.dumps({
            "signal_type": signal.signal_type,
            "dominant_side": signal.dominant_side,
            "long_usd": signal.long_usd,
            "short_usd": signal.short_usd,
        })
        
        entry = TradeLogEntry(
            timestamp=signal.timestamp,
            event_type="signal",
            trade_id=None,
            exchange=None,
            side=signal.dominant_side,
            size=signal.liquidation_usd,
            price=None,
            pnl=None,
            is_dry_run=is_dry_run,
            details=details,
        )
        
        async with self._buffer_lock:
            self._buffer.append(entry)
        
        self._start_flush_task()
    
    async def log_order_placed(
        self,
        trade_id: str,
        exchange: str,
        side: str,
        size: float,
        price: float,
        is_dry_run: bool,
    ) -> None:
        """Log order placement.
        
        Args:
            trade_id: UUID of the associated TradePair
            exchange: "polymarket" or "binance"
            side: "UP", "DOWN", "LONG", or "SHORT"
            size: Order size in USD
            price: Order price
            is_dry_run: Whether this is a dry run trade
        """
        entry = TradeLogEntry(
            timestamp=datetime.now(timezone.utc),
            event_type="order_placed",
            trade_id=trade_id,
            exchange=exchange,
            side=side,
            size=size,
            price=price,
            pnl=None,
            is_dry_run=is_dry_run,
            details=None,
        )
        
        async with self._buffer_lock:
            self._buffer.append(entry)
        
        self._start_flush_task()
    
    async def log_order_filled(
        self,
        trade_id: str,
        exchange: str,
        side: str,
        size: float,
        fill_price: float,
        is_dry_run: bool,
    ) -> None:
        """Log order fill.
        
        Args:
            trade_id: UUID of the associated TradePair
            exchange: "polymarket" or "binance"
            side: "UP", "DOWN", "LONG", or "SHORT"
            size: Fill size in USD
            fill_price: Actual fill price
            is_dry_run: Whether this is a dry run trade
        """
        entry = TradeLogEntry(
            timestamp=datetime.now(timezone.utc),
            event_type="order_filled",
            trade_id=trade_id,
            exchange=exchange,
            side=side,
            size=size,
            price=fill_price,
            pnl=None,
            is_dry_run=is_dry_run,
            details=None,
        )
        
        async with self._buffer_lock:
            self._buffer.append(entry)
        
        self._start_flush_task()
    
    async def log_position_closed(
        self,
        trade_id: str,
        exchange: str,
        pnl: float,
        is_dry_run: bool,
    ) -> None:
        """Log position closure with PnL.
        
        Args:
            trade_id: UUID of the associated TradePair
            exchange: "polymarket" or "binance"
            pnl: Realized PnL from the position
            is_dry_run: Whether this is a dry run trade
        """
        entry = TradeLogEntry(
            timestamp=datetime.now(timezone.utc),
            event_type="position_closed",
            trade_id=trade_id,
            exchange=exchange,
            side=None,
            size=None,
            price=None,
            pnl=pnl,
            is_dry_run=is_dry_run,
            details=None,
        )
        
        async with self._buffer_lock:
            self._buffer.append(entry)
        
        self._start_flush_task()
    
    async def flush(self) -> None:
        """Force flush pending writes to disk."""
        async with self._buffer_lock:
            if not self._buffer:
                return
            
            entries_to_write = self._buffer.copy()
            self._buffer.clear()
        
        # Write all buffered entries
        for entry in entries_to_write:
            self._write_entry(entry)
        
        # Flush file to disk
        if self._current_file is not None:
            self._current_file.flush()
    
    async def close(self) -> None:
        """Flush and close file handles."""
        # Stop the flush loop
        self._running = False
        
        if self._flush_task is not None and not self._flush_task.done():
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
        
        # Final flush
        await self.flush()
        
        # Close file handle
        if self._current_file is not None:
            self._current_file.close()
            self._current_file = None
            self._csv_writer = None
            self._current_date = None
