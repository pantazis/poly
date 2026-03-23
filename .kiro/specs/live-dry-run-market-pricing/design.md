# Design Document: Live Dry-Run Market Pricing

## Overview

This design introduces a narrow enhancement to the dry-run trading path: use read-only Polymarket market data as the authoritative source for dry-run option pricing whenever configured, and make the resulting notifications clear about which values are Polymarket option prices versus BTC reference prices.

The design deliberately does not alter live trading behavior or expand dry run into real order placement. It only improves how dry-run pricing is sourced and communicated.

Validates: Requirements 1, 2, 3, 4, 5

## Current Gap

The bot already models dry-run Polymarket orders and can optionally use live market discovery, but the user-facing behavior still permits synthetic-looking output that can be mistaken for real market pricing. The missing contract is not only data access, but also clear source-of-truth rules for dry-run pricing and fallback disclosure.

Validates: Requirements 1, 3, 4

## Design Goals

1. Use public read-only Polymarket data as the first-choice price source in dry run
2. Derive dry-run order metrics from the live option price rather than a fixed placeholder
3. Preserve safe dry-run semantics with no authenticated order submission
4. Make fallback behavior explicit in logs and predictable in tests
5. Clarify user-facing messages so Polymarket option prices are not confused with BTC reference prices

Validates: Requirements 1, 2, 3, 4

## Architecture Changes

### 1. Pricing Source Priority

The PolymarketConnector becomes the authoritative source for dry-run option pricing.

Priority order:

1. Live read-only Polymarket option price when `use_live_market_data_in_dry_run` is enabled and fetch succeeds
2. Explicit simulated fallback price when live pricing is disabled
3. Explicit simulated fallback price only after logged failure when live pricing is enabled but unavailable

This keeps Polymarket option price ownership inside the PolymarketConnector instead of allowing dry-run presentation values to drift from the actual market source.

Validates: Requirements 1, 2, 3, 5

### 2. Dry-Run Order Derivation

The simulated order path should compute presentation values from the chosen option price source.

Inputs:

- selected outcome: `UP` or `DOWN`
- current Polymarket option price
- configured discount percent
- configured bet size

Derived outputs:

- simulated entry price
- shares bought
- max profit
- max loss

These outputs should be materialized onto the existing PolymarketOrder model so downstream components do not need separate dry-run pricing logic.

Validates: Requirements 1, 2

### 3. Fallback Contract

Fallback behavior should be centralized and explicit.

Rules:

1. If live dry-run pricing is disabled, use the simulated fallback path without warning noise
2. If live dry-run pricing is enabled and the read-only request fails, emit a warning with enough context to diagnose the failure
3. If product preference is to continue, continue with a clearly identified fallback price
4. If product preference is to block, fail fast before producing a misleading trade entry message

The implementation may choose either continue-with-warning or block-on-failure, but it must be consistent and test-covered.

Validates: Requirements 3, 5

### 4. Notification Semantics

Telegram and other user-facing trade summaries should preserve a strict labeling distinction:

- `Entry Price` means Polymarket option entry price
- `Reference BTC Entry` means BTC context price, not option price
- `Reference BTC Exit` means BTC context price at close, not option settlement price

This is a presentation contract, not a trading-logic change. It prevents users from reading a BTC price as if it were the option premium.

Validates: Requirements 4

## Component Impact

### PolymarketConnector

- Owns live read-only price fetch for dry run
- Applies configured discount to produce simulated entry price
- Computes and stores derived dry-run trade metrics
- Emits explicit logs when fallback is used

Validates: Requirements 1, 2, 3

### TradingConfig / ConfigManager

- Exposes and loads the dry-run live Polymarket pricing flag
- Documents behavior in config surface

Validates: Requirements 5

### MessageFormatter / TelegramNotifier

- Preserves clear field names for option price versus BTC reference values
- Avoids ambiguous wording in entry and close messages

Validates: Requirements 4

## Test Strategy

1. Unit tests for PolymarketConnector price-source selection
2. Unit tests for derived dry-run metrics from live option prices
3. Unit tests for fallback logging and behavior when live read-only pricing fails
4. Notification formatting tests that verify Polymarket option price and BTC reference labels remain distinct

Validates: Requirements 1, 2, 3, 4