"""Tests for DataStore."""

import asyncio
from datetime import datetime, timezone
from pathlib import Path

from src.models import LiquidationEvent
from src.datastore import DataStore


def _make_event(time: datetime, symbol: str = "BTCUSDT") -> LiquidationEvent:
    """Helper to create a test event."""
    return LiquidationEvent(
        exchange="binance",
        symbol=symbol,
        side="long_liquidated",
        usd_size=50000.0,
        price=50000.0,
        time=time,
        is_significant=True,
    )


def test_creates_directory_if_missing(tmp_path: Path):
    """DataStore should create data directory if it doesn't exist."""
    data_dir = tmp_path / "new_dir"
    assert not data_dir.exists()
    
    store = DataStore(data_dir)
    
    assert data_dir.exists()
    asyncio.run(store.close())


def test_writes_csv_with_headers(tmp_path: Path):
    """DataStore should write CSV headers on new file."""
    store = DataStore(tmp_path)
    event = _make_event(datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc))
    
    asyncio.run(store.write(event))
    asyncio.run(store.close())
    
    csv_file = tmp_path / "liquidations_2024-01-15.csv"
    assert csv_file.exists()
    
    content = csv_file.read_text()
    lines = content.strip().split("\n")
    assert lines[0] == "exchange,symbol,side,usd_size,price,time,is_significant"
    assert len(lines) == 2


def test_daily_file_rotation(tmp_path: Path):
    """Events on different days should go to different files."""
    store = DataStore(tmp_path)
    
    event1 = _make_event(datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc))
    event2 = _make_event(datetime(2024, 1, 16, 12, 0, 0, tzinfo=timezone.utc))
    
    asyncio.run(store.write(event1))
    asyncio.run(store.write(event2))
    asyncio.run(store.close())
    
    assert (tmp_path / "liquidations_2024-01-15.csv").exists()
    assert (tmp_path / "liquidations_2024-01-16.csv").exists()
