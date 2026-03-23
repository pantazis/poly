# Requirements Document

## Introduction

This document specifies the requirements for a Liquidation Trading Bot that extends the existing Liquidation Data Collector. The bot monitors real-time liquidation data from Binance and executes a momentum-based trading strategy: placing directional bets on Polymarket's 5-minute binary options and hedging with inverse positions on Binance Futures at 3x leverage.

**⚠️ RISK WARNING:** This system implements an extremely high-risk trading strategy with effective leverage of ~2,400x on Polymarket positions. Without a proven edge (>54% win rate), this strategy will result in consistent losses. This is essentially gambling with leverage. Users should only risk capital they can afford to lose entirely.

## Strategy Overview

The trading strategy follows the "Mundave" approach:
1. **Entry Signal**: When liquidations reach $25,000-$100,000 threshold within a time window
2. **Polymarket Position**: Bet on price direction based on liquidation type
   - Long liquidations (price going DOWN) → Buy "DOWN" on Polymarket
   - Short liquidations (price going UP) → Buy "UP" on Polymarket
3. **Hedge Position**: Inverse position on Binance at 3x leverage
   - If betting UP on Polymarket → Short on Binance
   - If betting DOWN on Polymarket → Long on Binance
4. **Order Execution**: Place orders at 10% below current price for better entries

## API Research Summary

### Polymarket API
- **CLOB API**: Central Limit Order Book for placing/managing orders
- **Authentication**: Requires Ethereum wallet signature (EIP-712)
- **Order Types**: Limit orders with price in USDC
- **Markets**: 5-minute BTC binary options (UP/DOWN outcomes)
- **Settlement**: Automatic at expiry based on price movement

### Binance Futures API (Authenticated)
- **REST Endpoint**: `https://fapi.binance.com`
- **Authentication**: API Key + HMAC SHA256 signature
- **Leverage**: Configurable up to 125x (we use 3x)
- **Order Types**: Market, Limit, Stop-Loss
- **Margin Mode**: Cross or Isolated (recommend Isolated for risk control)

## Glossary

- **Trading_Bot**: The main system that orchestrates trade execution based on liquidation signals
- **Signal_Detector**: Component that monitors liquidation aggregations and detects entry signals
- **Polymarket_Connector**: Component that interfaces with Polymarket CLOB API for order placement
- **Binance_Trader**: Component that interfaces with Binance Futures API for hedge positions
- **Position_Manager**: Component that tracks open positions and manages lifecycle
- **Risk_Controller**: Component that enforces position limits and risk parameters
- **Trade_Logger**: Component that records all trade activity for analysis
- **Entry_Signal**: A condition where liquidations reach the threshold, triggering a trade
- **Polymarket_Position**: A bet on Polymarket's 5-minute binary option (UP or DOWN)
- **Hedge_Position**: An inverse leveraged position on Binance Futures
- **Trade_Pair**: A combined Polymarket bet and Binance hedge opened together
- **Liquidation_Window**: The time period over which liquidations are aggregated (default: 5 minutes)
- **Entry_Threshold_Min**: Minimum liquidation USD amount to trigger entry ($25,000)
- **Entry_Threshold_Max**: Maximum liquidation USD amount for entry ($100,000)
- **Bet_Size**: The USD amount wagered on Polymarket per trade ($10)
- **Hedge_Size**: The USD amount used for Binance hedge position
- **Hedge_Leverage**: The leverage multiplier for Binance hedge (3x)
- **Discount_Percent**: The percentage below current price for limit orders (10%)

## Requirements

### Requirement 1: Signal Detection

**User Story:** As a trader, I want the bot to detect entry signals from liquidation data, so that I can enter trades at optimal momentum points.

#### Acceptance Criteria

1. THE Signal_Detector SHALL subscribe to aggregation updates from the existing Liquidation_Collector
2. WHEN the 5-minute window shows total liquidations >= Entry_Threshold_Min AND <= Entry_Threshold_Max, THE Signal_Detector SHALL generate an Entry_Signal
3. THE Entry_Signal SHALL include:
   - `signal_type`: "long_liquidation" or "short_liquidation" (whichever is dominant)
   - `liquidation_usd`: Total USD liquidated in the window
   - `timestamp`: Time of signal generation
   - `dominant_side`: The side with higher liquidation volume
4. WHEN long_liquidated_usd > short_liquidated_usd in the window, THE Signal_Detector SHALL classify signal_type as "long_liquidation"
5. WHEN short_liquidated_usd > long_liquidated_usd in the window, THE Signal_Detector SHALL classify signal_type as "short_liquidation"
6. IF long_liquidated_usd equals short_liquidated_usd, THEN THE Signal_Detector SHALL NOT generate a signal
7. THE Signal_Detector SHALL NOT generate a new signal while a Trade_Pair is already open

### Requirement 2: Polymarket Order Execution

**User Story:** As a trader, I want the bot to place orders on Polymarket, so that I can bet on price direction based on liquidation momentum.

#### Acceptance Criteria

1. WHEN an Entry_Signal with signal_type "long_liquidation" is received, THE Polymarket_Connector SHALL place a BUY order for the "DOWN" outcome
2. WHEN an Entry_Signal with signal_type "short_liquidation" is received, THE Polymarket_Connector SHALL place a BUY order for the "UP" outcome
3. THE Polymarket_Connector SHALL place limit orders at Discount_Percent (10%) below the current best ask price
4. THE Polymarket_Connector SHALL use Bet_Size ($10) as the order amount
5. THE Polymarket_Connector SHALL authenticate using EIP-712 wallet signature
6. IF the Polymarket order fails to fill within 30 seconds, THEN THE Polymarket_Connector SHALL cancel the order and notify Position_Manager
7. WHEN a Polymarket order is filled, THE Polymarket_Connector SHALL emit a fill event with order details

### Requirement 3: Binance Hedge Execution

**User Story:** As a trader, I want the bot to place hedge positions on Binance, so that I can reduce directional risk on my Polymarket bets.

#### Acceptance Criteria

1. WHEN a Polymarket order is filled for "UP" outcome, THE Binance_Trader SHALL open a SHORT position on BTCUSDT
2. WHEN a Polymarket order is filled for "DOWN" outcome, THE Binance_Trader SHALL open a LONG position on BTCUSDT
3. THE Binance_Trader SHALL set position leverage to Hedge_Leverage (3x)
4. THE Binance_Trader SHALL use isolated margin mode for the hedge position
5. THE Binance_Trader SHALL calculate position size as: Hedge_Size / current_price × Hedge_Leverage
6. THE Binance_Trader SHALL place market orders for immediate execution
7. THE Binance_Trader SHALL authenticate using API key and HMAC SHA256 signature
8. IF the Binance order fails, THEN THE Binance_Trader SHALL retry up to 3 times with 1-second delays
9. IF all Binance order retries fail, THEN THE Binance_Trader SHALL log an error and notify Position_Manager of unhedged position

### Requirement 4: Position Management

**User Story:** As a trader, I want the bot to track and manage open positions, so that I know my current exposure and can close positions properly.

#### Acceptance Criteria

1. THE Position_Manager SHALL track all open Trade_Pairs with their entry details
2. THE Position_Manager SHALL store for each Trade_Pair:
   - `trade_id`: Unique identifier
   - `polymarket_order_id`: Polymarket order reference
   - `binance_position_id`: Binance position reference
   - `direction`: "UP" or "DOWN"
   - `entry_time`: Timestamp of entry
   - `polymarket_entry_price`: Fill price on Polymarket
   - `binance_entry_price`: Fill price on Binance
   - `status`: "pending", "open", "closing", "closed"
3. WHEN the Polymarket option expires (5 minutes from entry), THE Position_Manager SHALL close the Binance hedge position
4. WHEN closing a hedge, THE Binance_Trader SHALL place a market order to close the position
5. THE Position_Manager SHALL calculate and record PnL for each closed Trade_Pair
6. THE Position_Manager SHALL allow only one open Trade_Pair at a time

### Requirement 5: Risk Controls

**User Story:** As a trader, I want the bot to enforce risk limits, so that I don't lose more than I can afford.

#### Acceptance Criteria

1. THE Risk_Controller SHALL enforce a configurable maximum daily loss limit (default: $100)
2. WHEN daily realized losses reach the maximum daily loss limit, THE Risk_Controller SHALL block new Entry_Signals until the next UTC day
3. THE Risk_Controller SHALL enforce a configurable maximum concurrent positions limit (default: 1)
4. THE Risk_Controller SHALL verify sufficient balance on both Polymarket and Binance before allowing new trades
5. IF Polymarket balance < Bet_Size, THEN THE Risk_Controller SHALL block new trades and log a warning
6. IF Binance available margin < required margin for hedge, THEN THE Risk_Controller SHALL block new trades and log a warning
7. THE Risk_Controller SHALL track and expose current daily PnL

### Requirement 6: Trade Logging

**User Story:** As a trader, I want all trades logged, so that I can analyze performance and debug issues.

#### Acceptance Criteria

1. THE Trade_Logger SHALL record all Entry_Signals with their parameters
2. THE Trade_Logger SHALL record all order placements with exchange, side, size, and price
3. THE Trade_Logger SHALL record all order fills with actual fill price and quantity
4. THE Trade_Logger SHALL record all position closes with PnL
5. THE Trade_Logger SHALL persist logs to daily CSV files with naming pattern: `trades_YYYY-MM-DD.csv`
6. THE Trade_Logger SHALL include CSV headers: timestamp, event_type, trade_id, exchange, side, size, price, pnl, details
7. THE Trade_Logger SHALL flush writes to disk at least every 5 seconds

### Requirement 7: Configuration Management

**User Story:** As a trader, I want to configure trading parameters, so that I can adjust the strategy without code changes.

#### Acceptance Criteria

1. THE Trading_Bot SHALL load configuration from a YAML file
2. THE Trading_Bot SHALL support these configurable parameters:
   - `entry_threshold_min`: Minimum liquidation threshold (default: $25,000)
   - `entry_threshold_max`: Maximum liquidation threshold (default: $100,000)
   - `bet_size`: Polymarket bet amount (default: $10)
   - `hedge_leverage`: Binance leverage (default: 3)
   - `discount_percent`: Limit order discount (default: 10)
   - `max_daily_loss`: Daily loss limit (default: $100)
   - `liquidation_window_minutes`: Aggregation window (default: 5)
3. THE Trading_Bot SHALL validate configuration on startup and reject invalid values
4. IF a configuration value is missing, THEN THE Trading_Bot SHALL use the default value
5. IF a configuration value is invalid (negative bet_size, leverage > 20, etc.), THEN THE Trading_Bot SHALL exit with an error message

### Requirement 8: Exchange Connectivity

**User Story:** As a trader, I want the bot to maintain reliable connections to exchanges, so that I don't miss trades due to connectivity issues.

#### Acceptance Criteria

1. THE Polymarket_Connector SHALL verify API connectivity on startup
2. THE Binance_Trader SHALL verify API connectivity and permissions on startup
3. IF Polymarket API is unreachable, THEN THE Trading_Bot SHALL log an error and exit
4. IF Binance API is unreachable, THEN THE Trading_Bot SHALL log an error and exit
5. WHEN an API request fails due to rate limiting, THE Trading_Bot SHALL wait and retry with exponential backoff
6. THE Trading_Bot SHALL log all API errors with request details for debugging

### Requirement 9: Graceful Shutdown

**User Story:** As an operator, I want the bot to shut down gracefully, so that positions are properly managed during restarts.

#### Acceptance Criteria

1. WHEN a shutdown signal (SIGINT/SIGTERM) is received, THE Trading_Bot SHALL stop accepting new Entry_Signals
2. WHEN shutting down with open positions, THE Trading_Bot SHALL close all Binance hedge positions
3. WHEN shutting down, THE Trade_Logger SHALL flush all pending writes before exiting
4. THE Trading_Bot SHALL complete shutdown within 30 seconds of receiving the signal
5. IF position closure fails during shutdown, THEN THE Trading_Bot SHALL log the open position details for manual intervention

### Requirement 10: Dry Run Mode

**User Story:** As a trader, I want to test the bot without real money, so that I can validate the strategy before going live.

#### Acceptance Criteria

1. THE Trading_Bot SHALL support a dry_run configuration option (default: true)
2. WHILE dry_run is enabled, THE Trading_Bot SHALL simulate order placement without submitting orders to Polymarket or Binance
3. WHILE dry_run is enabled, THE Trading_Bot SHALL log simulated orders with "[DRY RUN]" prefix
4. WHILE dry_run is enabled, THE Trading_Bot SHALL calculate simulated Polymarket entry prices, shares bought, max profit, and max loss from read-only Polymarket market data when configured to do so
5. THE Trade_Logger SHALL record dry run trades with a `is_dry_run` flag set to true
6. WHILE dry_run is enabled and read-only Polymarket market data is unavailable, THE Trading_Bot SHALL either block simulated order placement or fall back to explicitly logged simulated prices
