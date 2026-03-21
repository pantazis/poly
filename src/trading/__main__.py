"""Main entry point for the Liquidation Trading Bot.

Usage:
    python -m src.trading --config config.yaml
    python -m src.trading  # Uses default config.yaml
"""

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path

from dotenv import load_dotenv

from src.collector import LiquidationCollector
from src.models import CollectorConfig

from .bot import TradingBot
from .config import ConfigManager, ConfigValidationError


logger = logging.getLogger(__name__)


def setup_logging() -> None:
    """Configure logging with timestamp format."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Liquidation Trading Bot - Automated trading based on liquidation signals"
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config.yaml"),
        help="Path to YAML configuration file (default: config.yaml)",
    )
    return parser.parse_args()


async def run_bot(config_path: Path) -> None:
    """Load configuration and run the trading bot.
    
    Args:
        config_path: Path to the YAML configuration file
    """
    # Load and validate configuration
    logger.info(f"Loading configuration from {config_path}")
    try:
        trading_config = ConfigManager.load(config_path)
    except FileNotFoundError:
        logger.error(f"Configuration file not found: {config_path}")
        sys.exit(1)
    except ConfigValidationError as e:
        logger.error(f"Configuration validation failed: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Failed to load configuration: {e}")
        sys.exit(1)
    
    logger.info("Configuration loaded successfully")
    logger.info(f"  Dry run mode: {trading_config.dry_run}")
    logger.info(f"  Entry threshold: ${trading_config.entry_threshold_min:,.0f} - ${trading_config.entry_threshold_max:,.0f}")
    logger.info(f"  Bet size: ${trading_config.bet_size:.2f}")
    logger.info(f"  Hedge leverage: {trading_config.hedge_leverage}x")
    logger.info(f"  Max daily loss: ${trading_config.max_daily_loss:.2f}")
    
    # Initialize LiquidationCollector with default config
    collector_config = CollectorConfig(
        significance_threshold_usd=trading_config.entry_threshold_min,
    )
    collector = LiquidationCollector(collector_config)
    
    # Initialize TradingBot
    bot = TradingBot(config=trading_config, collector=collector)
    
    # Set up signal handlers for graceful shutdown
    shutdown_requested = False
    
    async def handle_shutdown() -> None:
        nonlocal shutdown_requested
        if shutdown_requested:
            return
        shutdown_requested = True
        logger.info("Shutdown signal received")
        await bot.shutdown()
    
    # Unix signal handlers
    if sys.platform != "win32":
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(
                sig,
                lambda: asyncio.create_task(handle_shutdown())
            )
    
    # Start the collector in background
    collector_task = asyncio.create_task(collector.start())
    
    # Start the trading bot
    try:
        await bot.start()
    except KeyboardInterrupt:
        # Handle KeyboardInterrupt for Windows compatibility
        logger.info("KeyboardInterrupt received")
        await handle_shutdown()
    finally:
        # Ensure collector is also shut down
        await collector.shutdown()
        collector_task.cancel()
        try:
            await collector_task
        except asyncio.CancelledError:
            pass


def main() -> None:
    """Main entry point."""
    # Load environment variables from .env file
    load_dotenv()
    
    # Fix for aiodns on Windows - needs SelectorEventLoop
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    setup_logging()
    args = parse_args()
    
    logger.info("=" * 60)
    logger.info("Liquidation Trading Bot")
    logger.info("=" * 60)
    
    try:
        asyncio.run(run_bot(args.config))
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)
    
    logger.info("Trading bot stopped")


if __name__ == "__main__":
    main()
