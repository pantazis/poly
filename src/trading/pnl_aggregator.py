"""PnL aggregation component for the Liquidation Trading Bot.

This module provides CSV-based PnL aggregation for trade logs,
supporting single-day and date range queries.
"""

import csv
import logging
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path


logger = logging.getLogger(__name__)


@dataclass
class PnLSummary:
    """Aggregated PnL statistics for a date range.
    
    Attributes:
        start_date: Start date of the aggregation period
        end_date: End date of the aggregation period (inclusive)
        total_pnl: Sum of all PnL values in the period
        trade_count: Total number of closed trades
        win_count: Number of trades with positive PnL
        loss_count: Number of trades with negative or zero PnL
        win_rate: Ratio of winning trades (0.0 to 1.0)
    """
    start_date: date
    end_date: date
    total_pnl: float
    trade_count: int
    win_count: int
    loss_count: int
    win_rate: float


class PnLAggregator:
    """Reads CSV trade logs and calculates PnL statistics.
    
    Parses trade log CSV files to aggregate PnL data for specified
    date ranges. Handles missing files and malformed rows gracefully.
    
    Attributes:
        log_dir: Directory containing trade log CSV files
    """
    
    def __init__(self, log_dir: Path) -> None:
        """Initialize the PnLAggregator.
        
        Args:
            log_dir: Directory containing trade log CSV files
                     with pattern trades_YYYY-MM-DD.csv
        """
        self.log_dir = log_dir
    
    def _get_file_path(self, target_date: date) -> Path:
        """Get the CSV file path for a given date.
        
        Args:
            target_date: The date to get the file path for
            
        Returns:
            Path to the trade log CSV file for the given date
        """
        date_str = target_date.strftime("%Y-%m-%d")
        return self.log_dir / f"trades_{date_str}.csv"
    
    def _parse_csv_file(self, file_path: Path) -> list[float]:
        """Parse a CSV file and extract PnL values from position_closed events.
        
        Args:
            file_path: Path to the CSV file to parse
            
        Returns:
            List of PnL values from position_closed events
        """
        pnl_values: list[float] = []
        
        if not file_path.exists():
            logger.debug(f"Trade log file not found: {file_path}")
            return pnl_values
        
        try:
            with open(file_path, "r", newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                
                for row_num, row in enumerate(reader, start=2):  # Start at 2 (header is row 1)
                    try:
                        event_type = row.get("event_type", "").strip()
                        
                        # Only process position_closed events
                        if event_type != "position_closed":
                            continue
                        
                        pnl_str = row.get("pnl", "").strip()
                        
                        if not pnl_str:
                            logger.warning(
                                f"Missing pnl value in {file_path} at row {row_num}"
                            )
                            continue
                        
                        pnl = float(pnl_str)
                        pnl_values.append(pnl)
                        
                    except (ValueError, KeyError) as e:
                        logger.warning(
                            f"Malformed row in {file_path} at row {row_num}: {e}"
                        )
                        continue
                        
        except (OSError, csv.Error) as e:
            logger.warning(f"Error reading trade log file {file_path}: {e}")
        
        return pnl_values
    
    def _calculate_summary(
        self,
        start_date: date,
        end_date: date,
        pnl_values: list[float],
    ) -> PnLSummary:
        """Calculate PnL summary statistics from a list of PnL values.
        
        Args:
            start_date: Start date of the aggregation period
            end_date: End date of the aggregation period
            pnl_values: List of PnL values to aggregate
            
        Returns:
            PnLSummary with calculated statistics
        """
        total_pnl = sum(pnl_values)
        trade_count = len(pnl_values)
        win_count = sum(1 for pnl in pnl_values if pnl > 0)
        loss_count = sum(1 for pnl in pnl_values if pnl <= 0)
        win_rate = win_count / trade_count if trade_count > 0 else 0.0
        
        return PnLSummary(
            start_date=start_date,
            end_date=end_date,
            total_pnl=total_pnl,
            trade_count=trade_count,
            win_count=win_count,
            loss_count=loss_count,
            win_rate=win_rate,
        )
    
    def get_pnl_for_date(self, target_date: date) -> PnLSummary:
        """Get PnL summary for a single day.
        
        Args:
            target_date: The date to query PnL for
            
        Returns:
            PnLSummary for the specified date
        """
        file_path = self._get_file_path(target_date)
        pnl_values = self._parse_csv_file(file_path)
        
        return self._calculate_summary(target_date, target_date, pnl_values)
    
    def get_pnl_for_range(self, start_date: date, end_date: date) -> PnLSummary:
        """Get PnL summary for a date range (inclusive).
        
        Args:
            start_date: Start date of the range (inclusive)
            end_date: End date of the range (inclusive)
            
        Returns:
            PnLSummary for the specified date range
        """
        all_pnl_values: list[float] = []
        
        # Iterate through each date in the range
        current_date = start_date
        while current_date <= end_date:
            file_path = self._get_file_path(current_date)
            pnl_values = self._parse_csv_file(file_path)
            all_pnl_values.extend(pnl_values)
            current_date += timedelta(days=1)
        
        return self._calculate_summary(start_date, end_date, all_pnl_values)
