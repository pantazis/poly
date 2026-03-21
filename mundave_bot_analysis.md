# Mundave's Poly Market Bot - Strategy Analysis

Based on the transcripts, here's how his bot works:

---

## Core Strategy: Liquidation Momentum + Hedge

### Part 1: Entry Signal (Poly Market)

**Trigger:** Monitor liquidation data from exchanges (Binance, Hyperliquid)

**Logic:**
- When liquidations reach between **$25,000 - $100,000** threshold:
  - **Long liquidations** (people getting liquidated on longs) → Price going DOWN → **Buy "DOWN"** on Poly Market
  - **Short liquidations** (people getting liquidated on shorts) → Price going UP → **Buy "UP"** on Poly Market

**Rationale:** Liquidations create momentum. When someone gets liquidated, it triggers more liquidations in the same direction (cascade effect).

> "Once there's 25,000 liquidations... let me go ahead and take the trade. If it's short liquidations, that means price is going up, I want to buy up. If it's long liquidation, that means price is going down, I want to buy down."

---

### Part 2: The Hedge (Hyperliquid)

**Inverse position on Hyperliquid at 3x leverage:**
- If **long on Poly Market** (betting UP) → **Short on Hyperliquid**
- If **short on Poly Market** (betting DOWN) → **Long on Hyperliquid**

> "The second half of the trade is a little hedge with Hyperliquid. So on the other side of this trade, if I'm long, I'll be short on Hyperliquid."

---

## Data Sources Used

| Data Point | Source | Purpose |
|------------|--------|---------|
| Liquidation stream | Binance/Hyperliquid API | Entry signal trigger |
| Position sizes | Exchange data layer | See where big positions are |
| Distance to liquidation | Calculated | Predict upcoming liquidations |
| CVD (Cumulative Volume Delta) | Tick data | Directional bias |
| 1m/5m/10m/15m liquidation amounts | Aggregated | Momentum strength |

---

## Order Execution

**Discount bidding:** Places orders at **10% below current price** to get better entries

> "It buys the down at a 10% discount. So you can change that discount however you want."

---

## Key Parameters (from code scroll)

- **Bet size:** $10
- **Duration:** 300 seconds (5 minutes)
- **Liquidation range:** $25,000 - $100,000
- **Hedge leverage:** 3x on Hyperliquid
- **Total exposure per trade:** $25

---

## Why This Market?

**5-minute binary = ~2,400x effective leverage**

- You pay ~$50 for a contract that pays $100
- If BTC moves even 1 cent in your direction, you win 100%
- 288 trading opportunities per day
- Defined risk (can't lose more than your bet)
- No stop-loss management needed

---

## ML Model Results (from testing)

| Model | Accuracy | Notes |
|-------|----------|-------|
| XGBoost | 57.34% | Best at high confidence (143 trades) |
| LightGBM | 56% | Microstructure features |
| TabNet | 50.86% | Trash for this use case |
| TCN | 49.91% | Complete failure |

**Verdict:** Need >54% to break even. Only works with **confidence filtering** - trade only when model is highly confident.

---

## Risk Warning

He repeatedly emphasizes this is essentially **gambling with extreme leverage**:
> "2,400x leverage is way too much... Without a real edge, you're just paying the spread to Poly Market and slowly bleeding. At 288 bets per day, a 49% win rate drains you fast."
