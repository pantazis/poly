# Requirements Document: Live Dry-Run Market Pricing

## Introduction

This document specifies a focused enhancement to dry-run behavior for the liquidation trading bot. The goal is to stop relying on fixed placeholder prices for dry-run Polymarket trade presentation when live read-only Polymarket data is available, and instead use public market data so entry pricing, share counts, and payoff estimates reflect the actual market state.

This slice is intentionally limited to read-only pricing and user-visible dry-run outputs. It does not change live trading behavior or authorize real order submission in dry run mode.

## Problem Statement

The current dry-run flow can fall back to simulated or fixed values that make notifications look synthetic even when public Polymarket market data is available. This creates confusion about whether the bot is showing a real option price, a fixed placeholder, or a BTC reference price from another source.

## Glossary

- **Dry_Run_Live_Polymarket_Pricing**: Behavior where dry-run mode uses public Polymarket market data for pricing and market discovery without submitting orders
- **Polymarket_Option_Price**: The read-only best ask or equivalent market price for the selected UP or DOWN outcome
- **Simulated_Fallback_Price**: A locally generated placeholder price used only when live read-only pricing is disabled or unavailable
- **Trade_Presentation_Data**: User-visible dry-run values derived from the option price, including entry price, shares bought, max profit, and max loss
- **Reference_BTC_Price**: BTC price shown for context in notifications and settlement logic; distinct from the Polymarket option price

## Requirements

### Requirement 1: Read-Only Polymarket Pricing In Dry Run

**User Story:** As a bot operator, I want dry-run trades to use live read-only Polymarket option prices when available, so that entry notifications reflect the real market instead of fixed placeholder values.

#### Acceptance Criteria

1. WHEN dry_run is enabled AND live dry-run Polymarket pricing is enabled, THE Polymarket_Connector SHALL fetch the current option price for the selected outcome from public read-only Polymarket endpoints before simulating the order
2. THE Polymarket_Connector SHALL use the fetched Polymarket option price as the source input for dry-run order pricing calculations
3. THE Trading_Bot SHALL NOT substitute a fixed placeholder Polymarket option price when read-only Polymarket pricing succeeds
4. THE dry-run path SHALL continue to avoid submitting real Polymarket orders while using read-only market data

### Requirement 2: Derived Dry-Run Trade Metrics

**User Story:** As a trader, I want the dry-run trade metrics to be derived from the live Polymarket option price, so that shares bought, max profit, and max loss are realistic.

#### Acceptance Criteria

1. WHEN a dry-run Polymarket order is simulated using live read-only pricing, THE simulated entry price SHALL be derived from the fetched Polymarket option price after applying the configured discount behavior
2. THE simulated shares bought SHALL be calculated from bet_size divided by the simulated entry price
3. THE simulated max profit SHALL be calculated from the derived shares bought and stake amount
4. THE simulated max loss SHALL equal the configured stake amount
5. THE same derived values SHALL be stored on the PolymarketOrder model used by the rest of the trading flow

### Requirement 3: Explicit Fallback Behavior

**User Story:** As a bot operator, I want fallback behavior to be explicit, so that I know when the bot is using synthetic prices instead of live read-only Polymarket data.

#### Acceptance Criteria

1. IF live dry-run Polymarket pricing is disabled, THEN THE dry-run flow MAY use simulated fallback prices
2. IF live dry-run Polymarket pricing is enabled BUT read-only Polymarket pricing fails, THEN THE Trading_Bot SHALL either:
   - block the dry-run order simulation, or
   - continue only with an explicitly logged simulated fallback price
3. WHEN fallback pricing is used, THE system SHALL log that live Polymarket pricing was unavailable and that a simulated price was used
4. THE fallback path SHALL remain deterministic enough for tests to validate expected behavior

### Requirement 4: Notification Clarity

**User Story:** As a trader, I want Telegram trade messages to clearly distinguish Polymarket option price from BTC reference prices, so that I understand what each price means.

#### Acceptance Criteria

1. THE trade entry notification SHALL continue to show the Polymarket entry price as the option price used for the simulated or filled trade
2. IF a BTC context price is shown in the same message, THEN THE notification SHALL label it as a reference BTC price and not as the Polymarket option price
3. THE trade close notification SHALL preserve the distinction between Polymarket PnL and any BTC reference entry or exit values shown for context
4. THE bot SHALL NOT present a fixed placeholder Polymarket option price as though it were live market data

### Requirement 5: Configuration Surface

**User Story:** As a bot operator, I want configuration to control live dry-run Polymarket pricing explicitly, so that the behavior is predictable and safe.

#### Acceptance Criteria

1. THE TradingConfig SHALL expose a boolean setting controlling whether dry-run mode uses live read-only Polymarket pricing
2. THE configuration file SHALL document that enabling this setting uses read-only Polymarket market data without placing real Polymarket orders
3. THE configuration default SHALL preserve safe dry-run operation
4. IF the setting is disabled, THEN the bot SHALL remain capable of fully simulated dry-run execution