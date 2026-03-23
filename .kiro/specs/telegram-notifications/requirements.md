# Requirements Document

## Introduction

This document specifies the requirements for a Telegram Notifications feature that integrates with the existing Liquidation Trading Bot. The feature provides real-time notifications for all bot lifecycle events and supports interactive commands for querying PnL, bot status, and account balances. Messages clearly distinguish between dry run and live trading modes.

## Glossary

- **Telegram_Notifier**: Component that sends formatted messages to Telegram via the Bot API
- **Telegram_Command_Handler**: Component that receives and processes Telegram commands from users
- **PnL_Aggregator**: Component that reads CSV trade logs and calculates profit/loss for date ranges
- **Balance_Checker**: Component that queries Polymarket USDC balance and Binance margin balance
- **Bot_Lifecycle_Event**: Events including startup, shutdown, signals, trades, and errors
- **Trade_Log_CSV**: Daily CSV files at `./logs/trades_YYYY-MM-DD.csv` with trade event records
- **Mode_Indicator**: Visual prefix "[DRY RUN]" or "[LIVE]" shown in all notification messages

## Requirements

### Requirement 1: Telegram Configuration

**User Story:** As a bot operator, I want to configure Telegram notifications via environment variables, so that I can enable/disable notifications without code changes.

#### Acceptance Criteria

1. THE Telegram_Notifier SHALL read configuration from environment variables: TELEGRAM_ENABLED, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
2. WHEN TELEGRAM_ENABLED is "false" or unset, THE Telegram_Notifier SHALL disable all notification sending
3. WHEN TELEGRAM_ENABLED is "true" AND TELEGRAM_TOKEN is empty, THE Trading_Bot SHALL log a warning and disable notifications
4. WHEN TELEGRAM_ENABLED is "true" AND TELEGRAM_CHAT_ID is empty, THE Trading_Bot SHALL log a warning and disable notifications
5. THE Telegram_Notifier SHALL read trading mode from the existing TradingConfig.dry_run setting to determine Mode_Indicator

### Requirement 2: Bot Lifecycle Notifications

**User Story:** As a bot operator, I want to receive notifications for bot startup and shutdown, so that I know when the bot is running.

#### Acceptance Criteria

1. WHEN the Trading_Bot starts successfully, THE Telegram_Notifier SHALL send a startup message containing:
   - Mode_Indicator ("[DRY RUN]" or "[LIVE]")
   - Timestamp
   - Configuration summary (bet_size, hedge_size, hedge_leverage, max_daily_loss)
2. WHEN the Trading_Bot shuts down, THE Telegram_Notifier SHALL send a shutdown message containing:
   - Mode_Indicator
   - Timestamp
   - Shutdown reason (graceful, error, or signal)
   - Session summary (trades executed, total PnL)
3. WHEN exchange connectivity fails during startup, THE Telegram_Notifier SHALL send an error notification before the bot exits

### Requirement 3: Signal Notifications

**User Story:** As a trader, I want to receive notifications when entry signals are detected, so that I can monitor trading activity.

#### Acceptance Criteria

1. WHEN an Entry_Signal is detected, THE Telegram_Notifier SHALL send a signal notification containing:
   - Mode_Indicator
   - Signal type (long_liquidation or short_liquidation)
   - Total liquidation USD amount
   - Timestamp
2. WHEN a signal is blocked by Risk_Controller, THE Telegram_Notifier SHALL send a blocked signal notification with the reason

### Requirement 4: Trade Notifications

**User Story:** As a trader, I want to receive notifications for trade executions, so that I can track my positions in real-time.

#### Acceptance Criteria

1. WHEN a Polymarket order is filled, THE Telegram_Notifier SHALL send a trade entry notification containing:
   - Mode_Indicator
   - Trade ID
   - Direction (UP/DOWN)
   - Entry price
   - Bet size
   - Reference BTC entry price when available
2. WHEN a Binance hedge is opened, THE Telegram_Notifier SHALL send a hedge notification containing:
   - Mode_Indicator
   - Trade ID
   - Side (LONG/SHORT)
   - Entry price
   - Leverage
3. WHEN a Trade_Pair is closed, THE Telegram_Notifier SHALL send a trade close notification containing:
   - Mode_Indicator
   - Trade ID
   - Polymarket PnL
   - Binance PnL
   - Total PnL
   - Daily PnL running total
   - Reference BTC entry and exit prices when available

### Requirement 5: Error Notifications

**User Story:** As a bot operator, I want to receive notifications for errors, so that I can respond to issues quickly.

#### Acceptance Criteria

1. WHEN an API error occurs on Polymarket or Binance, THE Telegram_Notifier SHALL send an error notification containing:
   - Mode_Indicator
   - Error type
   - Exchange name
   - Error message
   - Timestamp
2. WHEN the daily loss limit is reached, THE Telegram_Notifier SHALL send a risk alert notification
3. WHEN a position fails to close during shutdown, THE Telegram_Notifier SHALL send a critical alert with position details for manual intervention
4. THE Telegram_Notifier SHALL NOT send duplicate error notifications for the same error within 60 seconds

### Requirement 6: Message Deduplication

**User Story:** As a bot operator, I want to avoid duplicate notifications, so that I don't get spammed with repeated messages.

#### Acceptance Criteria

1. THE Telegram_Notifier SHALL track recently sent messages using a hash of message content
2. THE Telegram_Notifier SHALL NOT send a message if an identical message was sent within the last 60 seconds
3. THE Telegram_Notifier SHALL clear the deduplication cache every 5 minutes to prevent memory growth

### Requirement 7: PnL Query Command

**User Story:** As a trader, I want to query my PnL for a date range via Telegram, so that I can check performance without accessing the server.

#### Acceptance Criteria

1. WHEN the user sends "/pnl" command, THE Telegram_Command_Handler SHALL return today's PnL summary
2. WHEN the user sends "/pnl YYYY-MM-DD" command, THE Telegram_Command_Handler SHALL return PnL for that specific date
3. WHEN the user sends "/pnl YYYY-MM-DD YYYY-MM-DD" command, THE Telegram_Command_Handler SHALL return PnL for the date range (inclusive)
4. THE PnL_Aggregator SHALL read from Trade_Log_CSV files in the configured log directory
5. THE PnL_Aggregator SHALL aggregate PnL from all "position_closed" events in the date range
6. THE PnL response SHALL include:
   - Date range queried
   - Total PnL
   - Number of trades
   - Win/loss count
   - Win rate percentage
7. IF no trade logs exist for the requested date range, THEN THE Telegram_Command_Handler SHALL respond with "No trades found for the specified period"

### Requirement 8: Status Query Command

**User Story:** As a bot operator, I want to check bot status via Telegram, so that I can verify the bot is running correctly.

#### Acceptance Criteria

1. WHEN the user sends "/status" command, THE Telegram_Command_Handler SHALL return bot status containing:
   - Mode_Indicator
   - Bot running state (running/stopped)
   - Current open position (if any) with direction and entry time
   - Daily PnL
   - Daily loss limit remaining
   - Uptime duration
2. THE Telegram_Command_Handler SHALL respond within 5 seconds

### Requirement 9: Balance Query Command

**User Story:** As a trader, I want to check my exchange balances via Telegram, so that I can monitor available funds.

#### Acceptance Criteria

1. WHEN the user sends "/balance" command, THE Balance_Checker SHALL query both exchanges and return:
   - Mode_Indicator
   - Polymarket USDC balance
   - Binance available margin balance
   - Total combined balance
2. WHILE TradingConfig.dry_run is True, THE Balance_Checker SHALL return simulated balances (mock values)
3. IF an exchange API call fails, THEN THE Telegram_Command_Handler SHALL respond with partial results and indicate which exchange failed

### Requirement 10: Human-Readable Message Formatting

**User Story:** As a bot operator, I want notifications to be easy to read, so that I can quickly understand the bot's status.

#### Acceptance Criteria

1. THE Telegram_Notifier SHALL format all messages using Telegram's MarkdownV2 syntax
2. THE Telegram_Notifier SHALL use emoji indicators for message types:
   - 🟢 for startup/success
   - 🔴 for shutdown/errors
   - 📊 for signals
   - 💰 for trades
   - ⚠️ for warnings
   - 🚨 for critical alerts
3. THE Telegram_Notifier SHALL format USD amounts with 2 decimal places and thousand separators
4. THE Telegram_Notifier SHALL format timestamps in UTC with format "YYYY-MM-DD HH:MM:SS UTC"
5. THE Mode_Indicator SHALL appear at the start of every notification message in bold format
