"""Tests for the TradeLogger component."""

import asyncio
import csv
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.trading.models import EntrySignal
from src.trading.trade_logger import TradeLogger


@pytest.fixture
def temp_log_dir():
    """Create a temporary directory for log files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
async def logger(temp_log_dir):
    """Create a TradeLogger instance with a temporary directory."""
    logger = TradeLogger(log_dir=temp_log_dir, flush_interval_seconds=0.1)
    yield logger
    await logger.close()


class TestTradeLoggerInit:
    """Tests for TradeLogger initialization."""
    
    def test_creates_log_directory(self, temp_log_dir):
        """Test that log directory is created if it doesn't exist."""
        new_dir = temp_log_dir / "nested" / "logs"
        logger = TradeLogger(log_dir=new_dir)
        assert new_dir.exists()
    
    def test_default_flush_interval(self, temp_log_dir):
        """Test default flush interval is 5 seconds."""
        logger = TradeLogger(log_dir=temp_log_dir)
        assert logger.flush_interval_seconds == 5.0
    
    def test_custom_flush_interval(self, temp_log_dir):
        """Test custom flush interval is set correctly."""
        logger = TradeLogger(log_dir=temp_log_dir, flush_interval_seconds=10.0)
        assert logger.flush_interval_seconds == 10.0


class TestLogSignal:
    """Tests for log_signal method."""
    
    @pytest.mark.asyncio
    async def test_log_signal_creates_entry(self, logger, temp_log_dir):
        """Test that log_signal creates a log entry."""
        signal = EntrySignal(
            signal_type="long_liquidation",
            liquidation_usd=50000.0,
            timestamp=datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
            dominant_side="long_liquidated",
            long_usd=35000.0,
            short_usd=15000.0,
        )
        
        await logger.log_signal(signal, is_dry_run=True)
        await logger.flush()
        
        # Check file was created
        log_file = temp_log_dir / "trades_2024-01-15.csv"
        assert log_file.exists()
        
        # Check content
        with open(log_file, "r") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        
        assert len(rows) == 1
        row = rows[0]
        assert row["event_type"] == "signal"
        assert row["is_dry_run"] == "true"
        assert row["size"] == "50000.0"
        assert "long_liquidation" in row["details"]
    
    @pytest.mark.asyncio
    async def test_log_signal_dry_run_false(self, logger, temp_log_dir):
        """Test that is_dry_run=False is logged correctly."""
        signal = EntrySignal(
            signal_type="short_liquidation",
            liquidation_usd=30000.0,
            timestamp=datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
            dominant_side="short_liquidated",
            long_usd=10000.0,
            short_usd=20000.0,
        )
        
        await logger.log_signal(signal, is_dry_run=False)
        await logger.flush()
        
        log_file = temp_log_dir / "trades_2024-01-15.csv"
        with open(log_file, "r") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        
        assert rows[0]["is_dry_run"] == "false"


class TestLogOrderPlaced:
    """Tests for log_order_placed method."""
    
    @pytest.mark.asyncio
    async def test_log_order_placed(self, logger, temp_log_dir):
        """Test that order placement is logged correctly."""
        await logger.log_order_placed(
            trade_id="test-uuid-123",
            exchange="polymarket",
            side="DOWN",
            size=10.0,
            price=0.45,
            is_dry_run=True,
        )
        await logger.flush()
        
        # Find the log file (date is current)
        log_files = list(temp_log_dir.glob("trades_*.csv"))
        assert len(log_files) == 1
        
        with open(log_files[0], "r") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        
        assert len(rows) == 1
        row = rows[0]
        assert row["event_type"] == "order_placed"
        assert row["trade_id"] == "test-uuid-123"
        assert row["exchange"] == "polymarket"
        assert row["side"] == "DOWN"
        assert row["size"] == "10.0"
        assert row["price"] == "0.45"


class TestLogOrderFilled:
    """Tests for log_order_filled method."""
    
    @pytest.mark.asyncio
    async def test_log_order_filled(self, logger, temp_log_dir):
        """Test that order fill is logged correctly."""
        await logger.log_order_filled(
            trade_id="test-uuid-456",
            exchange="binance",
            side="SHORT",
            size=15.0,
            fill_price=45000.0,
            is_dry_run=False,
        )
        await logger.flush()
        
        log_files = list(temp_log_dir.glob("trades_*.csv"))
        assert len(log_files) == 1
        
        with open(log_files[0], "r") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        
        assert len(rows) == 1
        row = rows[0]
        assert row["event_type"] == "order_filled"
        assert row["trade_id"] == "test-uuid-456"
        assert row["exchange"] == "binance"
        assert row["side"] == "SHORT"
        assert row["price"] == "45000.0"
        assert row["is_dry_run"] == "false"


class TestLogPositionClosed:
    """Tests for log_position_closed method."""
    
    @pytest.mark.asyncio
    async def test_log_position_closed_with_profit(self, logger, temp_log_dir):
        """Test that position close with profit is logged correctly."""
        await logger.log_position_closed(
            trade_id="test-uuid-789",
            exchange="binance",
            pnl=5.50,
            is_dry_run=True,
        )
        await logger.flush()
        
        log_files = list(temp_log_dir.glob("trades_*.csv"))
        with open(log_files[0], "r") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        
        assert len(rows) == 1
        row = rows[0]
        assert row["event_type"] == "position_closed"
        assert row["trade_id"] == "test-uuid-789"
        assert row["exchange"] == "binance"
        assert row["pnl"] == "5.5"
    
    @pytest.mark.asyncio
    async def test_log_position_closed_with_loss(self, logger, temp_log_dir):
        """Test that position close with loss is logged correctly."""
        await logger.log_position_closed(
            trade_id="test-uuid-abc",
            exchange="polymarket",
            pnl=-10.0,
            is_dry_run=False,
        )
        await logger.flush()
        
        log_files = list(temp_log_dir.glob("trades_*.csv"))
        with open(log_files[0], "r") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        
        assert rows[0]["pnl"] == "-10.0"


class TestDailyFileRotation:
    """Tests for daily CSV file rotation."""
    
    @pytest.mark.asyncio
    async def test_different_dates_create_different_files(self, logger, temp_log_dir):
        """Test that entries on different dates go to different files."""
        # Log signal for Jan 15
        signal1 = EntrySignal(
            signal_type="long_liquidation",
            liquidation_usd=50000.0,
            timestamp=datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
            dominant_side="long_liquidated",
            long_usd=35000.0,
            short_usd=15000.0,
        )
        await logger.log_signal(signal1, is_dry_run=True)
        
        # Log signal for Jan 16
        signal2 = EntrySignal(
            signal_type="short_liquidation",
            liquidation_usd=40000.0,
            timestamp=datetime(2024, 1, 16, 14, 0, 0, tzinfo=timezone.utc),
            dominant_side="short_liquidated",
            long_usd=15000.0,
            short_usd=25000.0,
        )
        await logger.log_signal(signal2, is_dry_run=True)
        
        await logger.flush()
        
        # Check both files exist
        file_jan15 = temp_log_dir / "trades_2024-01-15.csv"
        file_jan16 = temp_log_dir / "trades_2024-01-16.csv"
        
        assert file_jan15.exists()
        assert file_jan16.exists()
        
        # Check each file has correct content
        with open(file_jan15, "r") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            assert len(rows) == 1
            assert "long_liquidation" in rows[0]["details"]
        
        with open(file_jan16, "r") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            assert len(rows) == 1
            assert "short_liquidation" in rows[0]["details"]


class TestCSVHeaders:
    """Tests for CSV header format."""
    
    @pytest.mark.asyncio
    async def test_csv_has_correct_headers(self, logger, temp_log_dir):
        """Test that CSV files have the correct headers."""
        await logger.log_order_placed(
            trade_id="test",
            exchange="polymarket",
            side="UP",
            size=10.0,
            price=0.5,
            is_dry_run=True,
        )
        await logger.flush()
        
        log_files = list(temp_log_dir.glob("trades_*.csv"))
        with open(log_files[0], "r") as f:
            reader = csv.reader(f)
            headers = next(reader)
        
        expected_headers = [
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
        assert headers == expected_headers


class TestFlushAndClose:
    """Tests for flush and close methods."""
    
    @pytest.mark.asyncio
    async def test_flush_writes_buffered_entries(self, logger, temp_log_dir):
        """Test that flush writes all buffered entries to disk."""
        # Add multiple entries
        for i in range(5):
            await logger.log_order_placed(
                trade_id=f"test-{i}",
                exchange="polymarket",
                side="UP",
                size=10.0,
                price=0.5,
                is_dry_run=True,
            )
        
        # Flush
        await logger.flush()
        
        # Check all entries were written
        log_files = list(temp_log_dir.glob("trades_*.csv"))
        with open(log_files[0], "r") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        
        assert len(rows) == 5
    
    @pytest.mark.asyncio
    async def test_close_flushes_and_closes_file(self, logger, temp_log_dir):
        """Test that close flushes pending writes and closes file handles."""
        await logger.log_order_placed(
            trade_id="test",
            exchange="polymarket",
            side="UP",
            size=10.0,
            price=0.5,
            is_dry_run=True,
        )
        
        await logger.close()
        
        # Check entry was written
        log_files = list(temp_log_dir.glob("trades_*.csv"))
        with open(log_files[0], "r") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        
        assert len(rows) == 1
        
        # Check file handle is closed
        assert logger._current_file is None
    
    @pytest.mark.asyncio
    async def test_close_stops_flush_task(self, logger, temp_log_dir):
        """Test that close stops the background flush task."""
        # Start the flush task by logging something
        await logger.log_order_placed(
            trade_id="test",
            exchange="polymarket",
            side="UP",
            size=10.0,
            price=0.5,
            is_dry_run=True,
        )
        
        # Give the task time to start
        await asyncio.sleep(0.05)
        
        # Close should stop the task
        await logger.close()
        
        assert logger._running is False


class TestMultipleEntriesSameFile:
    """Tests for appending multiple entries to the same file."""
    
    @pytest.mark.asyncio
    async def test_append_to_existing_file(self, logger, temp_log_dir):
        """Test that entries are appended to existing files."""
        # First entry
        await logger.log_order_placed(
            trade_id="test-1",
            exchange="polymarket",
            side="UP",
            size=10.0,
            price=0.5,
            is_dry_run=True,
        )
        await logger.flush()
        
        # Second entry
        await logger.log_order_filled(
            trade_id="test-1",
            exchange="polymarket",
            side="UP",
            size=10.0,
            fill_price=0.48,
            is_dry_run=True,
        )
        await logger.flush()
        
        # Check both entries are in the file
        log_files = list(temp_log_dir.glob("trades_*.csv"))
        with open(log_files[0], "r") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        
        assert len(rows) == 2
        assert rows[0]["event_type"] == "order_placed"
        assert rows[1]["event_type"] == "order_filled"
