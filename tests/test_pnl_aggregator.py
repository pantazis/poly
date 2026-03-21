"""Tests for PnLAggregator component."""

import csv
from datetime import date
from pathlib import Path

import pytest

from src.trading.pnl_aggregator import PnLAggregator, PnLSummary


class TestPnLAggregator:
    """Tests for PnLAggregator class."""

    def test_get_pnl_for_date_with_trades(self, tmp_path: Path) -> None:
        """Test single day PnL aggregation with trades."""
        # Create a trade log file
        log_file = tmp_path / "trades_2024-01-15.csv"
        with open(log_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "timestamp", "event_type", "trade_id", "exchange",
                "side", "size", "price", "pnl", "is_dry_run", "details"
            ])
            # Position closed events with PnL
            writer.writerow([
                "2024-01-15T10:00:00+00:00", "position_closed", "trade-1",
                "polymarket", "", "", "", "50.25", "false", ""
            ])
            writer.writerow([
                "2024-01-15T11:00:00+00:00", "position_closed", "trade-2",
                "binance", "", "", "", "-20.50", "false", ""
            ])
            writer.writerow([
                "2024-01-15T12:00:00+00:00", "position_closed", "trade-3",
                "polymarket", "", "", "", "100.00", "false", ""
            ])
            # Non position_closed events should be ignored
            writer.writerow([
                "2024-01-15T09:00:00+00:00", "order_placed", "trade-1",
                "polymarket", "UP", "100", "0.55", "", "false", ""
            ])

        aggregator = PnLAggregator(tmp_path)
        summary = aggregator.get_pnl_for_date(date(2024, 1, 15))

        assert summary.start_date == date(2024, 1, 15)
        assert summary.end_date == date(2024, 1, 15)
        assert summary.total_pnl == pytest.approx(129.75)  # 50.25 - 20.50 + 100.00
        assert summary.trade_count == 3
        assert summary.win_count == 2  # 50.25 and 100.00
        assert summary.loss_count == 1  # -20.50
        assert summary.win_rate == pytest.approx(2 / 3)


    def test_get_pnl_for_date_missing_file(self, tmp_path: Path) -> None:
        """Test single day PnL when file doesn't exist."""
        aggregator = PnLAggregator(tmp_path)
        summary = aggregator.get_pnl_for_date(date(2024, 1, 15))

        assert summary.start_date == date(2024, 1, 15)
        assert summary.end_date == date(2024, 1, 15)
        assert summary.total_pnl == 0.0
        assert summary.trade_count == 0
        assert summary.win_count == 0
        assert summary.loss_count == 0
        assert summary.win_rate == 0.0

    def test_get_pnl_for_date_empty_file(self, tmp_path: Path) -> None:
        """Test single day PnL with empty file (headers only)."""
        log_file = tmp_path / "trades_2024-01-15.csv"
        with open(log_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "timestamp", "event_type", "trade_id", "exchange",
                "side", "size", "price", "pnl", "is_dry_run", "details"
            ])

        aggregator = PnLAggregator(tmp_path)
        summary = aggregator.get_pnl_for_date(date(2024, 1, 15))

        assert summary.total_pnl == 0.0
        assert summary.trade_count == 0

    def test_get_pnl_for_date_malformed_rows(self, tmp_path: Path) -> None:
        """Test handling of malformed rows in CSV."""
        log_file = tmp_path / "trades_2024-01-15.csv"
        with open(log_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "timestamp", "event_type", "trade_id", "exchange",
                "side", "size", "price", "pnl", "is_dry_run", "details"
            ])
            # Valid row
            writer.writerow([
                "2024-01-15T10:00:00+00:00", "position_closed", "trade-1",
                "polymarket", "", "", "", "50.00", "false", ""
            ])
            # Malformed pnl value
            writer.writerow([
                "2024-01-15T11:00:00+00:00", "position_closed", "trade-2",
                "binance", "", "", "", "invalid", "false", ""
            ])
            # Empty pnl value
            writer.writerow([
                "2024-01-15T12:00:00+00:00", "position_closed", "trade-3",
                "polymarket", "", "", "", "", "false", ""
            ])
            # Another valid row
            writer.writerow([
                "2024-01-15T13:00:00+00:00", "position_closed", "trade-4",
                "binance", "", "", "", "25.00", "false", ""
            ])

        aggregator = PnLAggregator(tmp_path)
        summary = aggregator.get_pnl_for_date(date(2024, 1, 15))

        # Should only count the 2 valid rows
        assert summary.total_pnl == pytest.approx(75.00)  # 50.00 + 25.00
        assert summary.trade_count == 2

    def test_get_pnl_for_range_multiple_days(self, tmp_path: Path) -> None:
        """Test date range PnL aggregation across multiple days."""
        # Create trade logs for 3 days
        for day, pnl_values in [
            (15, [50.00, -10.00]),
            (16, [100.00]),
            (17, [-30.00, 20.00]),
        ]:
            log_file = tmp_path / f"trades_2024-01-{day:02d}.csv"
            with open(log_file, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "timestamp", "event_type", "trade_id", "exchange",
                    "side", "size", "price", "pnl", "is_dry_run", "details"
                ])
                for i, pnl in enumerate(pnl_values):
                    writer.writerow([
                        f"2024-01-{day:02d}T{10+i:02d}:00:00+00:00",
                        "position_closed", f"trade-{day}-{i}",
                        "polymarket", "", "", "", str(pnl), "false", ""
                    ])

        aggregator = PnLAggregator(tmp_path)
        summary = aggregator.get_pnl_for_range(date(2024, 1, 15), date(2024, 1, 17))

        assert summary.start_date == date(2024, 1, 15)
        assert summary.end_date == date(2024, 1, 17)
        # 50 - 10 + 100 - 30 + 20 = 130
        assert summary.total_pnl == pytest.approx(130.00)
        assert summary.trade_count == 5
        assert summary.win_count == 3  # 50, 100, 20
        assert summary.loss_count == 2  # -10, -30
        assert summary.win_rate == pytest.approx(3 / 5)

    def test_get_pnl_for_range_with_missing_days(self, tmp_path: Path) -> None:
        """Test date range with some missing days."""
        # Only create file for day 15, skip 16, create for 17
        log_file = tmp_path / "trades_2024-01-15.csv"
        with open(log_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "timestamp", "event_type", "trade_id", "exchange",
                "side", "size", "price", "pnl", "is_dry_run", "details"
            ])
            writer.writerow([
                "2024-01-15T10:00:00+00:00", "position_closed", "trade-1",
                "polymarket", "", "", "", "50.00", "false", ""
            ])

        log_file = tmp_path / "trades_2024-01-17.csv"
        with open(log_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "timestamp", "event_type", "trade_id", "exchange",
                "side", "size", "price", "pnl", "is_dry_run", "details"
            ])
            writer.writerow([
                "2024-01-17T10:00:00+00:00", "position_closed", "trade-2",
                "polymarket", "", "", "", "30.00", "false", ""
            ])

        aggregator = PnLAggregator(tmp_path)
        summary = aggregator.get_pnl_for_range(date(2024, 1, 15), date(2024, 1, 17))

        assert summary.total_pnl == pytest.approx(80.00)  # 50 + 30
        assert summary.trade_count == 2

    def test_get_pnl_for_range_single_day(self, tmp_path: Path) -> None:
        """Test date range with same start and end date."""
        log_file = tmp_path / "trades_2024-01-15.csv"
        with open(log_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "timestamp", "event_type", "trade_id", "exchange",
                "side", "size", "price", "pnl", "is_dry_run", "details"
            ])
            writer.writerow([
                "2024-01-15T10:00:00+00:00", "position_closed", "trade-1",
                "polymarket", "", "", "", "75.00", "false", ""
            ])

        aggregator = PnLAggregator(tmp_path)
        summary = aggregator.get_pnl_for_range(date(2024, 1, 15), date(2024, 1, 15))

        assert summary.start_date == date(2024, 1, 15)
        assert summary.end_date == date(2024, 1, 15)
        assert summary.total_pnl == pytest.approx(75.00)
        assert summary.trade_count == 1

    def test_win_rate_with_zero_pnl(self, tmp_path: Path) -> None:
        """Test that zero PnL is counted as a loss."""
        log_file = tmp_path / "trades_2024-01-15.csv"
        with open(log_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "timestamp", "event_type", "trade_id", "exchange",
                "side", "size", "price", "pnl", "is_dry_run", "details"
            ])
            writer.writerow([
                "2024-01-15T10:00:00+00:00", "position_closed", "trade-1",
                "polymarket", "", "", "", "0.00", "false", ""
            ])
            writer.writerow([
                "2024-01-15T11:00:00+00:00", "position_closed", "trade-2",
                "polymarket", "", "", "", "10.00", "false", ""
            ])

        aggregator = PnLAggregator(tmp_path)
        summary = aggregator.get_pnl_for_date(date(2024, 1, 15))

        assert summary.trade_count == 2
        assert summary.win_count == 1  # Only 10.00
        assert summary.loss_count == 1  # 0.00 counts as loss
        assert summary.win_rate == pytest.approx(0.5)

    def test_filters_only_position_closed_events(self, tmp_path: Path) -> None:
        """Test that only position_closed events are counted."""
        log_file = tmp_path / "trades_2024-01-15.csv"
        with open(log_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "timestamp", "event_type", "trade_id", "exchange",
                "side", "size", "price", "pnl", "is_dry_run", "details"
            ])
            # Various event types
            writer.writerow([
                "2024-01-15T09:00:00+00:00", "signal", "",
                "", "long", "50000", "", "", "false", ""
            ])
            writer.writerow([
                "2024-01-15T09:01:00+00:00", "order_placed", "trade-1",
                "polymarket", "UP", "100", "0.55", "", "false", ""
            ])
            writer.writerow([
                "2024-01-15T09:02:00+00:00", "order_filled", "trade-1",
                "polymarket", "UP", "100", "0.55", "", "false", ""
            ])
            # Only this should be counted
            writer.writerow([
                "2024-01-15T10:00:00+00:00", "position_closed", "trade-1",
                "polymarket", "", "", "", "25.00", "false", ""
            ])

        aggregator = PnLAggregator(tmp_path)
        summary = aggregator.get_pnl_for_date(date(2024, 1, 15))

        assert summary.trade_count == 1
        assert summary.total_pnl == pytest.approx(25.00)
