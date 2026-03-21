# Requirements Document

## Introduction

This document specifies the requirements for a Liquidation Data Collection System that collects real-time liquidation events from Binance Futures. The system normalizes data, filters for significant events, and stores them for later analysis by the Mundave trading bot.

## API Research Summary

### Binance Futures API (FREE - No Authentication Required)
- **WebSocket Endpoint:** `wss://fstream.binance.com/ws/!forceOrder@arr`
- **Data:** All market liquidation orders streamed in real-time
- **Limitation:** Only latest liquidation per symbol within 1000ms is pushed (some throttling)
- **Connection:** Server sends ping every 3 minutes, must respond with pong within 10 minutes. Max connection duration: 24 hours.

**Binance forceOrder Message Format:**
```json
{
  "e": "forceOrder",
  "E": 1568014460893,
  "o": {
    "s": "BTCUSDT",
    "S": "SELL",
    "o": "LIMIT",
    "f": "IOC",
    "q": "0.014",
    "p": "9910",
    "ap": "9910",
    "X": "FILLED",
    "l": "0.014",
    "z": "0.014",
    "T": 1568014460893
  }
}
```

**Field Descriptions:**
- `e`: Event type ("forceOrder")
- `E`: Event time (milliseconds)
- `o.s`: Symbol (e.g., "BTCUSDT")
- `o.S`: Side - "SELL" = long liquidated (price down), "BUY" = short liquidated (price up)
- `o.q`: Original quantity
- `o.p`: Price
- `o.ap`: Average price
- `o.z`: Filled accumulated quantity
- `o.T`: Trade time (milliseconds)

### Hyperliquid (NOT INCLUDED)
Hyperliquid's official API does not provide a global liquidation stream. Only user-specific liquidation data is available, which requires knowing wallet addresses in advance. For simplicity, this system focuses on Binance only.

## Glossary

- **Liquidation_Collector**: The main system responsible for collecting, normalizing, and storing liquidation data
- **Binance_Connector**: Component that connects to Binance WebSocket stream for liquidation data
- **Data_Normalizer**: Component that transforms Binance data into unified format
- **Event_Filter**: Component that filters liquidation events based on USD size threshold
- **Data_Store**: Component responsible for persisting liquidation data to storage
- **Liquidation_Event**: A forced position closure on an exchange when margin requirements are not met
- **Long_Liquidation**: A liquidation of a long position, indicating downward price pressure
- **Short_Liquidation**: A liquidation of a short position, indicating upward price pressure
- **USD_Size**: The dollar value of a liquidation event (quantity × price)
- **Significance_Threshold**: The minimum USD size ($25,000) for a liquidation to be considered significant

## Requirements

### Requirement 1: Binance WebSocket Connection

**User Story:** As a data analyst, I want to receive real-time liquidation data from Binance Futures, so that I can track liquidation events on the largest crypto exchange.

#### Acceptance Criteria

1. WHEN the Liquidation_Collector starts, THE Binance_Connector SHALL establish a WebSocket connection to `wss://fstream.binance.com/ws/!forceOrder@arr`
2. THE Binance_Connector SHALL receive liquidation events without requiring API authentication
3. WHEN a `forceOrder` message is received, THE Binance_Connector SHALL extract:
   - `o.s` (symbol)
   - `o.S` (side: "SELL" or "BUY")
   - `o.p` (price)
   - `o.ap` (average price)
   - `o.z` (filled accumulated quantity)
   - `o.T` (trade time in milliseconds)
4. IF the WebSocket connection is lost, THEN THE Binance_Connector SHALL attempt reconnection with exponential backoff (1s, 2s, 4s, 8s, max 30s)
5. WHEN a ping frame is received from Binance server, THE Binance_Connector SHALL respond with a pong frame immediately
6. THE Binance_Connector SHALL reconnect before the 24-hour connection limit expires

### Requirement 2: Data Normalization

**User Story:** As a data analyst, I want liquidation data in a consistent format, so that I can analyze it easily.

#### Acceptance Criteria

1. WHEN a Binance liquidation event is received, THE Data_Normalizer SHALL transform it into the unified format
2. THE Data_Normalizer SHALL produce events with these fields:
   - `exchange`: "binance"
   - `symbol`: Trading pair (e.g., "BTCUSDT")
   - `side`: "long_liquidated" or "short_liquidated"
   - `usd_size`: Calculated as filled_quantity × average_price
   - `price`: Liquidation price
   - `time`: ISO 8601 timestamp in UTC
3. WHEN Binance reports side as "SELL", THE Data_Normalizer SHALL map it to "long_liquidated"
4. WHEN Binance reports side as "BUY", THE Data_Normalizer SHALL map it to "short_liquidated"
5. FOR ALL normalized events, parsing then serializing then parsing SHALL produce an equivalent object (round-trip property)

### Requirement 3: Significance Filtering

**User Story:** As a trader, I want to filter for significant liquidation events, so that I only track events that could impact price momentum.

#### Acceptance Criteria

1. THE Event_Filter SHALL have a configurable significance threshold with default value of $25,000
2. WHEN a normalized event has usd_size >= Significance_Threshold, THE Event_Filter SHALL mark it as significant
3. WHEN a normalized event has usd_size < Significance_Threshold, THE Event_Filter SHALL mark it as non-significant
4. THE Liquidation_Collector SHALL store both significant and non-significant events with their classification

### Requirement 4: Data Persistence

**User Story:** As a data analyst, I want liquidation data stored persistently, so that I can analyze historical patterns.

#### Acceptance Criteria

1. THE Data_Store SHALL persist all normalized liquidation events to CSV files
2. THE Data_Store SHALL create daily CSV files with naming pattern: `liquidations_YYYY-MM-DD.csv`
3. THE Data_Store SHALL include CSV headers: exchange, symbol, side, usd_size, price, time, is_significant
4. WHEN a new day begins (UTC), THE Data_Store SHALL create a new CSV file
5. IF the storage directory does not exist, THEN THE Data_Store SHALL create it on startup
6. THE Data_Store SHALL flush writes to disk at least every 5 seconds to prevent data loss

### Requirement 5: Time-Window Aggregation

**User Story:** As a trader, I want to see aggregated liquidation amounts over different time windows, so that I can assess momentum strength.

#### Acceptance Criteria

1. THE Liquidation_Collector SHALL maintain rolling aggregations for 1-minute, 5-minute, 10-minute, and 15-minute windows
2. WHEN queried, THE Liquidation_Collector SHALL return total long_liquidated USD and short_liquidated USD for each time window
3. THE Liquidation_Collector SHALL update aggregations in real-time as new events arrive
4. THE Liquidation_Collector SHALL remove events from aggregations when they fall outside the time window

### Requirement 6: System Health Monitoring

**User Story:** As an operator, I want to monitor the health of the data collection system, so that I can detect and respond to issues.

#### Acceptance Criteria

1. THE Liquidation_Collector SHALL log connection status changes for the Binance connector
2. THE Liquidation_Collector SHALL track and expose metrics: events_received_total, events_filtered_significant, connection_uptime_seconds
3. WHEN no events are received for 5 minutes from Binance, THE Liquidation_Collector SHALL log a warning
4. IF the Binance connection fails, THEN THE Liquidation_Collector SHALL log an error and continue retry attempts

### Requirement 7: Graceful Shutdown

**User Story:** As an operator, I want the system to shut down gracefully, so that no data is lost during restarts.

#### Acceptance Criteria

1. WHEN a shutdown signal (SIGINT/SIGTERM) is received, THE Liquidation_Collector SHALL close the WebSocket connection cleanly
2. WHEN shutting down, THE Data_Store SHALL flush all pending writes before exiting
3. THE Liquidation_Collector SHALL complete shutdown within 10 seconds of receiving the signal
