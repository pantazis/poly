# Implementation Plan: Live Dry-Run Market Pricing

## Overview

This plan implements a focused dry-run pricing enhancement for Polymarket option trades. The work keeps dry-run execution safe while making simulated trade pricing reflect public read-only Polymarket market data instead of fixed placeholder values.

## Tasks

- [ ] 1. Confirm pricing-source behavior in PolymarketConnector
  - [ ] 1.1 Review the dry-run `get_current_price()` and simulated order path in `src/trading/polymarket_connector.py`
    - Verify whether live read-only pricing already takes precedence when configured
    - Identify any remaining fixed placeholder path used for user-visible trade pricing
    - _Requirements: 1.1, 1.2, 1.3, 3.1_

- [ ] 2. Enforce live read-only Polymarket price as the primary dry-run source
  - [ ] 2.1 Update `src/trading/polymarket_connector.py`
    - Ensure the dry-run simulated order path derives entry price from read-only Polymarket data when enabled
    - Preserve dry-run safety by avoiding real order submission
    - _Requirements: 1.1, 1.2, 1.4, 2.1_

  - [ ] 2.2 Store derived trade presentation data on the Polymarket order model
    - Ensure entry price, shares bought, max profit, and max loss are derived from the chosen option price source
    - Reuse existing `PolymarketOrder` fields where available
    - _Requirements: 2.2, 2.3, 2.4, 2.5_

- [ ] 3. Make fallback behavior explicit and testable
  - [ ] 3.1 Update fallback handling in `src/trading/polymarket_connector.py`
    - Log when live read-only pricing fails and the connector falls back to simulation
    - Keep fallback behavior deterministic enough for unit tests
    - _Requirements: 3.1, 3.2, 3.3, 3.4_

- [ ] 4. Clarify notification wording
  - [ ] 4.1 Update `src/trading/message_formatter.py` and related notifier tests
    - Keep `Entry Price` as the Polymarket option price
    - Label BTC context values explicitly as reference BTC prices where shown
    - _Requirements: 4.1, 4.2, 4.3, 4.4_

- [ ] 5. Validate configuration surface
  - [ ] 5.1 Verify `src/trading/config.py` and `config.yaml`
    - Confirm the dry-run live Polymarket pricing flag is loaded and documented correctly
    - Preserve a safe dry-run default
    - _Requirements: 5.1, 5.2, 5.3, 5.4_

- [ ] 6. Add focused tests
  - [ ] 6.1 Extend `tests/test_polymarket_connector.py`
    - Add coverage for live read-only price precedence in dry run
    - Add coverage for fallback behavior when live pricing fails
    - _Requirements: 1.1, 1.3, 2.1, 3.2, 3.3_

  - [ ] 6.2 Extend `tests/test_message_formatter.py`
    - Verify user-visible distinction between Polymarket option price and BTC reference prices
    - _Requirements: 4.1, 4.2, 4.3_

  - [ ] 6.3 Extend integration-oriented trading bot tests where needed
    - Verify dry-run trade notifications use live-derived Polymarket option prices when configured
    - _Requirements: 1.1, 2.1, 4.1_

- [ ] 7. Checkpoint - Validate against the spec
  - [ ] 7.1 Run focused pytest coverage for connector, formatter, and bot dry-run notification behavior
    - _Requirements: 1, 2, 3, 4, 5_

## Notes

- This slice does not require changes to live trading order submission
- This slice does not require changing hedge execution semantics
- The preferred implementation is minimal and local to the Polymarket dry-run path and message formatting