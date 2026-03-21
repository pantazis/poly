"""DataStore - Persists liquidation events to daily CSV files."""

import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import TextIO

from .models import LiquidationEvent


class DataStore:
    """Persists liquidation events to daily CSV files."""
    
    CSV_HEADERS = ["exchange", "symbol", "side", "usd_size", "price", "time", "is_significant"]
    
    def __init__(self, data_dir: Path):
        """
        Args:
            data_dir: Directory for CSV files (created if not exists)
        """
        self._data_dir = data_dir
        self._data_dir.mkdir(parents=True, exist_ok=True)
        
        self._current_date: str | None = None
        self._file: TextIO | None = None
        self._writer: csv.writer | None = None
        self._buffer: list[LiquidationEvent] = []
    
    def _get_date_str(self, dt: datetime) -> str:
        """Get date string in YYYY-MM-DD format."""
        return dt.strftime("%Y-%m-%d")
    
    def _get_file_path(self, date_str: str) -> Path:
        """Get CSV file path for a given date."""
        return self._data_dir / f"liquidations_{date_str}.csv"
    
    def _ensure_file_open(self, date_str: str) -> None:
        """Ensure the correct file is open for the given date."""
        if self._current_date == date_str and self._file is not None:
            return
        
        # Close existing file if open
        if self._file is not None:
            self._file.close()
        
        # Open new file
        file_path = self._get_file_path(date_str)
        file_exists = file_path.exists()
        
        self._file = open(file_path, "a", newline="", encoding="utf-8")
        self._writer = csv.writer(self._file)
        self._current_date = date_str
        
        # Write headers if new file
        if not file_exists:
            self._writer.writerow(self.CSV_HEADERS)
            self._file.flush()
    
    async def write(self, event: LiquidationEvent) -> None:
        """
        Append event to current day's CSV file.
        Creates new file with headers if day changes.
        """
        self._buffer.append(event)
    
    async def flush(self) -> None:
        """Force flush pending writes to disk."""
        if not self._buffer:
            return
        
        # Group events by date
        events_by_date: dict[str, list[LiquidationEvent]] = {}
        for event in self._buffer:
            date_str = self._get_date_str(event.time)
            if date_str not in events_by_date:
                events_by_date[date_str] = []
            events_by_date[date_str].append(event)
        
        # Write each group to appropriate file
        for date_str, events in events_by_date.items():
            self._ensure_file_open(date_str)
            for event in events:
                self._writer.writerow([
                    event.exchange,
                    event.symbol,
                    event.side,
                    event.usd_size,
                    event.price,
                    event.time.isoformat(),
                    event.is_significant,
                ])
            self._file.flush()
        
        self._buffer.clear()
    
    async def close(self) -> None:
        """Flush and close file handles."""
        await self.flush()
        if self._file is not None:
            self._file.close()
            self._file = None
            self._writer = None
            self._current_date = None
