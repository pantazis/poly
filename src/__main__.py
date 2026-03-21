"""Main entry point for the Liquidation Data Collector."""

import argparse
import asyncio
import logging
from pathlib import Path

from .collector import LiquidationCollector
from .models import CollectorConfig


def setup_logging() -> None:
    """Configure logging."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Real-time Binance Futures liquidation data collector"
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("./data"),
        help="Directory for CSV files (default: ./data)",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=25_000.0,
        help="Significance threshold in USD (default: 25000)",
    )
    return parser.parse_args()


async def main() -> None:
    """Main entry point."""
    setup_logging()
    args = parse_args()
    
    config = CollectorConfig(
        data_dir=args.data_dir,
        significance_threshold_usd=args.threshold,
    )
    
    collector = LiquidationCollector(config)
    await collector.start()


if __name__ == "__main__":
    asyncio.run(main())
