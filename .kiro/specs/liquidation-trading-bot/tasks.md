# Implementation Plan: Liquidation Trading Bot

## Overview

This plan implements an automated trading bot that monitors liquidation data from the existing collector, places directional bets on Polymarket's 5-minute BTC binary options, and hedges with inverse positions on Binance Futures at 3x leverage. The implementation follows an incremental approach, building core data models first, then individual components, and finally wiring everything together.

## Tasks

- [ ] 1. Create core data models and configuration
  - [x] 1.1 Create trading bot data models in `src/trading/models.py`
    - Define `EntrySignal` dataclass with signal_type, liquidation_usd, timestamp, dominant_side, long_usd, short_usd
    - Define `PolymarketOrder` dataclass with order_id, market_id, outcome, side, size, price, status, fill_price, fill_time
    - Define `BinancePosition` dataclass with position_id, symbol, side, size, leverage, entry_price, margin_mode, status, pnl
    - Define `TradePair` dataclass with trade_id, polymarket_order, binance_position, direction, entry_time, expiry_time, status, pnl fields
    - Define `TradeLogEntry` dataclass with timestamp, event_type, trade_id, exchange, side, size, price, pnl, is_dry_run, details
    - _Requirements: 1.3, 4.2, 6.6_

  - [x] 1.2 Create `TradingConfig` dataclass and `ConfigManager` in `src/trading/config.py`
    - Define `TradingConfig` with all configurable parameters and defaults
    - Implement `ConfigManager.load()` to parse YAML with environment variable substitution
    - Implement `ConfigManager.validate()` to check value constraints
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5_

  - [ ]* 1.3 Write property tests for configuration validation
    - **Property 17: Configuration Default Values**
    - **Property 18: Configuration Validation**
    - **Validates: Requirements 7.2, 7.3, 7.4, 7.5**

- [ ] 2. Implement SignalDetector component
  - [x] 2.1 Create `SignalDetector` class in `src/trading/signal_detector.py`
    - Implement `__init__` with collector reference, thresholds, window_minutes, on_signal callback
    - Implement `start()` to begin polling aggregations at 1-second intervals
    - Implement `stop()` to halt monitoring
    - Implement `set_position_open()` to block signals when position is active
    - Implement `check_signal()` to evaluate aggregations against thresholds
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7_

  - [ ]* 2.2 Write property tests for signal detection
    - **Property 1: Signal Threshold Detection**
    - **Property 2: Signal Type Classification**
    - **Property 3: Entry Signal Data Completeness**
    - **Validates: Requirements 1.2, 1.3, 1.4, 1.5, 1.6, 1.7**

- [ ] 3. Implement PolymarketConnector component
  - [x] 3.1 Create `PolymarketConnector` class in `src/trading/polymarket_connector.py`
    - Implement `__init__` with private_key, api_url, dry_run flag
    - Implement `connect()` to verify API connectivity
    - Implement `get_balance()` to fetch USDC balance
    - Implement `get_current_price()` to get best ask for UP/DOWN outcomes
    - Implement `place_order()` with discount calculation, timeout handling, and order cancellation
    - Implement `cancel_order()` for pending orders
    - Add EIP-712 signature generation for authentication
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7_

  - [ ]* 3.2 Write property tests for Polymarket order logic
    - **Property 4: Signal to Polymarket Outcome Mapping**
    - **Property 5: Limit Order Discount Calculation**
    - **Validates: Requirements 2.1, 2.2, 2.3**

- [x] 4. Implement BinanceTrader component
  - [x] 4.1 Create `BinanceTrader` class in `src/trading/binance_trader.py`
    - Implement `__init__` with api_key, api_secret, api_url, dry_run flag
    - Implement `connect()` to verify API connectivity and permissions
    - Implement `get_available_margin()` to fetch available USDT margin
    - Implement `get_current_price()` to get mark price
    - Implement `set_leverage()` and `set_margin_mode()` for position setup
    - Implement `open_position()` with market order, retry logic (3 attempts), and position size calculation
    - Implement `close_position()` with market order
    - Add HMAC SHA256 signature generation for authentication
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9_

  - [ ]* 4.2 Write property tests for Binance hedge logic
    - **Property 6: Polymarket Outcome to Binance Hedge Mapping**
    - **Property 7: Binance Position Size Calculation**
    - **Validates: Requirements 3.1, 3.2, 3.5**

- [x] 5. Checkpoint - Verify core components
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 6. Implement PositionManager component
  - [x] 6.1 Create `PositionManager` class in `src/trading/position_manager.py`
    - Implement `__init__` with binance_trader reference and on_position_closed callback
    - Implement `has_open_position()` and `get_open_position()` for state queries
    - Implement `open_trade_pair()` to create TradePair with UUID, set expiry timer
    - Implement `close_trade_pair()` to close hedge and calculate PnL
    - Implement `check_expiries()` for periodic expiry checking
    - Implement `get_all_trades()` to return trade history
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6_

  - [ ]* 6.2 Write property tests for position management
    - **Property 8: Trade_Pair Data Completeness**
    - **Property 9: Position Expiry Timing**
    - **Property 10: PnL Calculation Correctness**
    - **Property 11: Single Position Limit**
    - **Validates: Requirements 4.1, 4.2, 4.3, 4.5, 4.6**

- [ ] 7. Implement RiskController component
  - [x] 7.1 Create `RiskController` class in `src/trading/risk_controller.py`
    - Implement `__init__` with max_daily_loss, max_concurrent_positions, connector references
    - Implement `record_pnl()` to track realized PnL
    - Implement `get_daily_pnl()` and `is_daily_limit_reached()` for limit checks
    - Implement `can_open_position()` to validate balance, margin, and limits
    - Implement `reset_daily_pnl()` for UTC midnight reset
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7_

  - [ ]* 7.2 Write property tests for risk controls
    - **Property 12: Daily Loss Limit Enforcement**
    - **Property 13: Balance Check Before Trade**
    - **Property 14: Daily PnL Tracking Accuracy**
    - **Validates: Requirements 5.1, 5.2, 5.4, 5.5, 5.6, 5.7**

- [ ] 8. Implement TradeLogger component
  - [x] 8.1 Create `TradeLogger` class in `src/trading/trade_logger.py`
    - Implement `__init__` with log_dir and flush_interval_seconds
    - Implement `log_signal()`, `log_order_placed()`, `log_order_filled()`, `log_position_closed()`
    - Implement daily CSV file rotation with pattern `trades_YYYY-MM-DD.csv`
    - Implement `flush()` for periodic disk writes
    - Implement `close()` for graceful shutdown
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7_

  - [ ]* 8.2 Write property tests for trade logging
    - **Property 15: Trade Event Logging Completeness**
    - **Property 16: Daily Log File Partitioning**
    - **Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5, 6.6**

- [x] 9. Checkpoint - Verify all components
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 10. Implement TradingBot orchestrator and wire components
  - [x] 10.1 Create `TradingBot` class in `src/trading/bot.py`
    - Implement `__init__` to instantiate all components with config
    - Implement `start()` to verify connectivity, start signal detection, and run event loop
    - Implement `shutdown()` with 30-second timeout, position closure, and log flushing
    - Implement `_handle_signal()` to process entry signals through risk checks and order placement
    - Implement `_handle_polymarket_fill()` to open Binance hedge after Polymarket fill
    - Wire SignalDetector → RiskController → PolymarketConnector → BinanceTrader → PositionManager → TradeLogger
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 9.1, 9.2, 9.3, 9.4, 9.5_

  - [x] 10.2 Implement dry run mode in all exchange connectors
    - Add simulated order/position creation without API calls
    - Use read-only Polymarket market data for dry-run pricing when configured
    - Set is_dry_run flag in all log entries
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5_

  - [ ]* 10.3 Write property tests for dry run mode
    - **Property 20: Dry Run Mode Behavior**
    - **Validates: Requirements 10.2, 10.3, 10.4, 10.5**

  - [ ]* 10.4 Write property tests for retry logic
    - **Property 19: Exponential Backoff Timing**
    - **Validates: Requirements 8.5**

- [ ] 11. Create entry point and CLI
  - [x] 11.1 Create `src/trading/__init__.py` with public exports
    - Export TradingBot, TradingConfig, ConfigManager
    - _Requirements: 7.1_

  - [x] 11.2 Create `src/trading/__main__.py` entry point
    - Parse command-line arguments for config file path
    - Load and validate configuration
    - Initialize LiquidationCollector from existing codebase
    - Initialize and start TradingBot
    - Handle SIGINT/SIGTERM for graceful shutdown
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5_

  - [x] 11.3 Create example `config.yaml` in project root
    - Include all configurable parameters with comments
    - Show environment variable substitution syntax
    - Set dry_run: true as default
    - _Requirements: 7.1, 7.2_

- [x] 12. Final checkpoint - Integration verification
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- The bot integrates with the existing LiquidationCollector in `src/collector.py`
- All new trading components go in `src/trading/` subdirectory to keep separation from collector code
- Dry run mode is enabled by default for safety
