# Implementation Plan: Telegram Notifications

## Overview

This plan implements Telegram notifications for the Liquidation Trading Bot. The implementation adds three new components (TelegramNotifier, TelegramCommandHandler, PnLAggregator) and integrates them with the existing TradingBot lifecycle. All messages include mode indicators ([DRY RUN] or [LIVE]) and use MarkdownV2 formatting with emojis.

## Tasks

- [x] 1. Extend TradingConfig with Telegram fields
  - [x] 1.1 Add telegram_enabled, telegram_token, telegram_chat_id fields to TradingConfig dataclass
    - Add fields with defaults: telegram_enabled=False, telegram_token="", telegram_chat_id=""
    - _Requirements: 1.1, 1.5_
  - [x] 1.2 Update ConfigManager to load Telegram settings from YAML and environment variables
    - Add telegram section parsing in ConfigManager.load()
    - Support ${TELEGRAM_TOKEN} and ${TELEGRAM_CHAT_ID} environment variable substitution
    - _Requirements: 1.1_
  - [ ]* 1.3 Write unit tests for Telegram configuration loading
    - Test enabled/disabled states, missing token/chat_id warnings
    - _Requirements: 1.2, 1.3, 1.4_

- [x] 2. Implement MessageFormatter utility
  - [x] 2.1 Create MessageFormatter class with MarkdownV2 formatting methods
    - Implement escape_markdown() for special character escaping
    - Implement format_usd() with 2 decimals and thousand separators
    - Implement format_timestamp() with "YYYY-MM-DD HH:MM:SS UTC" format
    - _Requirements: 10.1, 10.3, 10.4_
  - [x] 2.2 Implement message formatting methods for all notification types
    - format_startup(), format_shutdown(), format_signal(), format_trade_entry()
    - format_hedge_opened(), format_trade_closed(), format_error(), format_risk_alert()
    - Include mode indicator and emoji prefixes in all messages
    - _Requirements: 10.2, 10.5, 2.1, 2.2, 3.1, 3.2, 4.1, 4.2, 4.3, 5.1, 5.2_
  - [ ]* 2.3 Write property test for MarkdownV2 escaping
    - **Property 12: MarkdownV2 Escaping**
    - **Validates: Requirements 10.1**
  - [ ]* 2.4 Write property test for USD formatting
    - **Property 9: USD Formatting**
    - **Validates: Requirements 10.3**
  - [ ]* 2.5 Write property test for timestamp formatting
    - **Property 10: Timestamp Formatting**
    - **Validates: Requirements 10.4**

- [x] 3. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Implement TelegramNotifier
  - [x] 4.1 Create TelegramNotifier class with Telegram Bot API integration
    - Implement __init__ with token, chat_id, dry_run, enabled parameters
    - Implement _send_message() using aiohttp to POST to Telegram API
    - Handle API errors with retry logic (3 retries, exponential backoff)
    - _Requirements: 1.1, 1.2_
  - [x] 4.2 Implement message deduplication
    - Track message hashes with timestamps in a dict
    - Skip sending if identical message sent within 60 seconds
    - Clear entries older than 5 minutes periodically
    - _Requirements: 5.4, 6.1, 6.2, 6.3_
  - [x] 4.3 Implement notification methods
    - send_startup(), send_shutdown(), send_signal(), send_signal_blocked()
    - send_trade_entry(), send_hedge_opened(), send_trade_closed()
    - send_error(), send_risk_alert(), close()
    - _Requirements: 2.1, 2.2, 2.3, 3.1, 3.2, 4.1, 4.2, 4.3, 5.1, 5.2, 5.3_
  - [ ]* 4.4 Write property test for mode indicator correctness
    - **Property 3: Mode Indicator Correctness**
    - **Validates: Requirements 1.5, 10.5**
  - [ ]* 4.5 Write property test for deduplication within window
    - **Property 5: Deduplication Within Window**
    - **Validates: Requirements 5.4, 6.1, 6.2**

- [x] 5. Implement PnLAggregator
  - [x] 5.1 Create PnLSummary dataclass and PnLAggregator class
    - Define PnLSummary with start_date, end_date, total_pnl, trade_count, win_count, loss_count, win_rate
    - Implement __init__ with log_dir parameter
    - _Requirements: 7.4_
  - [x] 5.2 Implement CSV parsing and PnL calculation methods
    - Implement get_pnl_for_date() for single day queries
    - Implement get_pnl_for_range() for date range queries
    - Parse "position_closed" events and sum pnl values
    - Handle missing files and malformed rows gracefully
    - _Requirements: 7.1, 7.2, 7.3, 7.5, 7.6, 7.7_
  - [ ]* 5.3 Write property test for PnL aggregation correctness
    - **Property 7: PnL Aggregation Correctness**
    - **Validates: Requirements 7.2, 7.3, 7.4, 7.5, 7.6**

- [x] 6. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Implement TelegramCommandHandler
  - [x] 7.1 Create TelegramCommandHandler class with long polling
    - Implement __init__ with dependencies (notifier, pnl_aggregator, risk_controller, etc.)
    - Implement start() to begin polling loop
    - Implement stop() to gracefully stop polling
    - _Requirements: 7.1, 8.1, 9.1_
  - [x] 7.2 Implement /pnl command handler
    - Parse arguments: no args (today), single date, date range
    - Call PnLAggregator and format response using MessageFormatter
    - Handle invalid date formats with usage help
    - _Requirements: 7.1, 7.2, 7.3, 7.6, 7.7_
  - [x] 7.3 Implement /status command handler
    - Query bot state, open position, daily PnL, uptime
    - Format response with mode indicator
    - _Requirements: 8.1, 8.2_
  - [x] 7.4 Implement /balance command handler
    - Query Polymarket and Binance balances (mock in dry_run mode)
    - Handle partial failures with error indicators
    - _Requirements: 9.1, 9.2, 9.3_
  - [ ]* 7.5 Write property test for dry run simulated balances
    - **Property 13: Dry Run Returns Simulated Balances**
    - **Validates: Requirements 9.2**
  - [ ]* 7.6 Write unit tests for command handlers
    - Test /pnl with various date formats
    - Test /status response content
    - Test /balance with partial failures
    - _Requirements: 7.1, 7.2, 7.3, 8.1, 9.1, 9.3_

- [x] 8. Integrate with TradingBot lifecycle
  - [x] 8.1 Initialize Telegram components in TradingBot.__init__
    - Create TelegramNotifier if telegram_enabled
    - Create PnLAggregator with log_dir
    - Log warning if enabled but token/chat_id missing
    - _Requirements: 1.2, 1.3, 1.4_
  - [x] 8.2 Add startup notification in TradingBot.start()
    - Send startup message with config summary after exchange connectivity verified
    - Send error notification if connectivity fails before exit
    - Start TelegramCommandHandler polling
    - _Requirements: 2.1, 2.3_
  - [x] 8.3 Add shutdown notification in TradingBot.shutdown()
    - Calculate session trades and PnL
    - Send shutdown message with reason and summary
    - Stop TelegramCommandHandler
    - Close TelegramNotifier
    - _Requirements: 2.2_
  - [x] 8.4 Add signal notifications in TradingBot._handle_signal()
    - Send signal notification when signal detected
    - Send blocked signal notification when risk controller blocks
    - _Requirements: 3.1, 3.2_
  - [x] 8.5 Add trade notifications in TradingBot._handle_polymarket_fill()
    - Send trade entry notification after Polymarket fill
    - Send hedge notification after Binance position opened
    - _Requirements: 4.1, 4.2_
  - [x] 8.6 Add trade close notification in TradingBot._handle_position_closed()
    - Send trade close notification with PnL breakdown
    - Include daily PnL running total
    - _Requirements: 4.3_
  - [x] 8.7 Add error notifications for API failures
    - Send error notification on Polymarket/Binance API errors
    - Send risk alert when daily loss limit reached
    - Send critical alert for failed position close during shutdown
    - _Requirements: 5.1, 5.2, 5.3_

- [x] 9. Update configuration files
  - [x] 9.1 Add Telegram settings to config.yaml
    - Add telegram section with enabled, token, chat_id fields
    - Use environment variable substitution for secrets
    - _Requirements: 1.1_
  - [x] 9.2 Add Telegram environment variables to .env
    - Add TELEGRAM_ENABLED, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
    - Include comments explaining how to obtain bot token
    - _Requirements: 1.1_

- [x] 10. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 11. Include BTC reference prices in trade notifications
  - Show reference BTC entry price in trade entry notification when available
  - Show reference BTC entry and exit prices in trade close notification when available
  - _Requirements: 4.1, 4.3_

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- All notifications include mode indicator ([DRY RUN] or [LIVE]) at the start
- Message deduplication prevents spam for repeated errors
- TelegramCommandHandler uses long polling (not webhooks) for simplicity
- Property tests use hypothesis library for randomized input generation
