# Implementation Plan: Liquidation Data Collector

## Overview

This implementation plan creates a real-time Binance Futures liquidation data collector using Python with asyncio. The system connects to Binance WebSocket, normalizes events, filters by significance, persists to CSV, and maintains rolling aggregations.

## Tasks

- [x] 1. Set up project structure and core data models
  - Create project directory structure with `src/` and `tests/` folders
  - Set up `pyproject.toml` with dependencies: `websockets`, `pytest`, `hypothesis`
  - Create `LiquidationEvent` dataclass with all required fields
  - Create `WindowAggregation` and `HealthMetrics` dataclasses
  - Create `CollectorConfig` dataclass for configuration
  - _Requirements: 2.2, 5.1, 6.2_

- [-] 2. Implement DataNormalizer component
  - [x] 2.1 Implement DataNormalizer class
    - Create `normalize_binance()` static method to transform raw Binance messages
    - Implement side mapping: "SELL" → "long_liquidated", "BUY" → "short_liquidated"
    - Calculate `usd_size` as `filled_quantity × average_price`
    - Convert millisecond timestamps to UTC datetime
    - Implement `to_dict()` and `from_dict()` for serialization
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_

  - [ ]* 2.2 Write property test for side mapping correctness
    - **Property 1: Side Mapping Correctness**
    - **Validates: Requirements 2.3, 2.4**

  - [ ]* 2.3 Write property test for serialization round-trip
    - **Property 2: Serialization Round-Trip**
    - **Validates: Requirements 2.5**

  - [ ]* 2.4 Write property test for USD size calculation
    - **Property 4: USD Size Calculation**
    - **Validates: Requirements 2.2**

- [-] 3. Implement EventFilter component
  - [x] 3.1 Implement EventFilter class
    - Create constructor with configurable `threshold_usd` (default $25,000)
    - Implement `classify()` method that sets `is_significant` based on threshold
    - Add `threshold` property to expose current threshold value
    - _Requirements: 3.1, 3.2, 3.3, 3.4_

  - [ ]* 3.2 Write property test for significance classification
    - **Property 3: Significance Classification**
    - **Validates: Requirements 3.2, 3.3**

- [x] 4. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [-] 5. Implement DataStore component
  - [x] 5.1 Implement DataStore class
    - Create constructor that accepts `data_dir` Path and creates directory if missing
    - Implement `write()` async method to append events to daily CSV files
    - Create CSV files with headers: exchange, symbol, side, usd_size, price, time, is_significant
    - Implement daily file rotation with naming pattern `liquidations_YYYY-MM-DD.csv`
    - Implement `flush()` async method to force write pending data
    - Implement `close()` async method for graceful shutdown
    - Use buffered writes with flush every 5 seconds
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6_

  - [ ]* 5.2 Write property test for CSV persistence round-trip
    - **Property 5: CSV Persistence Round-Trip**
    - **Validates: Requirements 4.1**

  - [ ]* 5.3 Write property test for daily file partitioning
    - **Property 6: Daily File Partitioning**
    - **Validates: Requirements 4.2, 4.4**

- [-] 6. Implement TimeAggregator component
  - [x] 6.1 Implement TimeAggregator class
    - Create class with WINDOWS = [1, 5, 10, 15] minutes
    - Implement `add_event()` to add significant events to aggregation
    - Implement `get_aggregations()` to return WindowAggregation for all windows
    - Implement `prune_expired()` to remove events older than 15 minutes
    - Calculate separate totals for long_liquidated_usd and short_liquidated_usd
    - _Requirements: 5.1, 5.2, 5.3, 5.4_

  - [ ]* 6.2 Write property test for aggregation sum correctness
    - **Property 7: Aggregation Sum Correctness**
    - **Validates: Requirements 5.1, 5.2, 5.3**

  - [ ]* 6.3 Write property test for expired event exclusion
    - **Property 8: Expired Event Exclusion**
    - **Validates: Requirements 5.4**

- [x] 7. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [-] 8. Implement BinanceConnector component
  - [x] 8.1 Implement BinanceConnector class
    - Create constructor with `on_event` async callback parameter
    - Implement `connect()` async method to establish WebSocket to `wss://fstream.binance.com/ws/!forceOrder@arr`
    - Implement automatic ping/pong handling for Binance server pings
    - Implement exponential backoff reconnection: 1s, 2s, 4s, 8s, 16s, max 30s
    - Implement proactive reconnection before 24-hour limit (at 23 hours)
    - Implement `disconnect()` async method for graceful close
    - Add `is_connected` and `uptime_seconds` properties
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6_

  - [ ]* 8.2 Write property test for exponential backoff timing
    - **Property 10: Exponential Backoff Timing**
    - **Validates: Requirements 1.4**

- [-] 9. Implement HealthMonitor component
  - [x] 9.1 Implement HealthMonitor class
    - Create constructor that accepts BinanceConnector reference
    - Implement `record_event()` to track event counts and timestamps
    - Implement `get_metrics()` to return HealthMetrics dataclass
    - Implement `check_health()` async method that logs warning if no events for 5 minutes
    - Track: events_received_total, events_filtered_significant, connection_uptime_seconds
    - _Requirements: 6.1, 6.2, 6.3, 6.4_

  - [ ]* 9.2 Write property test for metrics accuracy
    - **Property 9: Metrics Accuracy**
    - **Validates: Requirements 6.2**

- [-] 10. Implement LiquidationCollector orchestrator
  - [x] 10.1 Implement LiquidationCollector class
    - Create constructor accepting CollectorConfig
    - Wire together all components: BinanceConnector, DataNormalizer, EventFilter, DataStore, TimeAggregator, HealthMonitor
    - Implement `start()` async method that runs until shutdown signal
    - Implement event processing pipeline: receive → normalize → classify → store → aggregate
    - Set up periodic health checks (every 30 seconds)
    - Set up periodic data flush (every 5 seconds)
    - Add `get_aggregations()` and `get_health()` methods for external queries
    - _Requirements: 1.1, 3.4, 5.3, 6.1_

  - [x] 10.2 Implement graceful shutdown
    - Register signal handlers for SIGINT and SIGTERM
    - Implement `shutdown()` async method with 10-second timeout
    - Close WebSocket connection with 5-second timeout
    - Flush and close DataStore with 4-second timeout
    - Log final metrics on shutdown
    - _Requirements: 7.1, 7.2, 7.3_

- [x] 11. Create main entry point
  - Create `__main__.py` with CLI argument parsing for data directory and threshold
  - Set up logging configuration
  - Instantiate and run LiquidationCollector
  - _Requirements: 1.1, 3.1_

- [x] 12. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Python 3.11+ required for asyncio improvements and dataclass features
- Use `websockets` library for WebSocket client
- Use `hypothesis` library for property-based testing with minimum 100 examples
- All timestamps should be UTC timezone-aware
- CSV files stored in configurable data directory (default: `./data`)
