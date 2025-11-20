# Enhanced Dynamic Grid Strategy

Your trading bot has been upgraded from a simple fixed-level grid to an **Enhanced Dynamic Grid Strategy** optimized for crypto volatility.

## Architecture Changes

### Core Components Added

1. **MarketAnalyzer** — Real-time market analysis
   - Fetches OHLC data from Binance API (1h + 4h candles)
   - Calculates ATR (Average True Range) for volatility measurement
   - Computes EMA20/EMA50 for trend detection
   - Detects volatility spikes (ATR > 1.5× average)

2. **GridStrategy** — Dynamic grid generator
   - Replaces fixed-level grids with **ATR-based spacing**
   - Trend-aware grid adjustment
   - Symmetrical take-profit (TP) layers
   - Emergency grid pause during volatility spikes

### Key Improvements

| Feature | Before | After |
|---------|--------|-------|
| **Grid Spacing** | Fixed % (drawdown) | Dynamic (ATR × 0.5) |
| **Trend Filter** | None | EMA20/EMA50 on 4h |
| **Take-Profit** | Manual/None | Automated, symmetrical |
| **Volatility Response** | None | Spike detection + grid pause |
| **Order Types** | Buy only | Buy + Sell (TP) layers |

## Configuration Parameters

```python
# Binance OHLC source
OHLC_INTERVAL = "1h"  # Fine-tuning entry
TREND_INTERVAL = "4h"  # Trend regime

# Volatility & Grid
ATR_PERIOD = 14              # Standard ATR period
GRID_SPACING = ATR × 0.5     # Grid level distance
TP_TARGET = GRID_SPACING × 1.5  # Take-profit offset

# Trend Detection
EMA_FAST = 20   # Fast exponential MA
EMA_SLOW = 50   # Slow exponential MA
TREND_THRESHOLD = 1%  # Hysteresis to avoid noise

# Risk Management
VOLATILITY_SPIKE_MULT = 1.5  # Alert when ATR > 1.5 × avg
SPIKE_DISABLE_GRIDS = True   # Pause grids on spike
```

## How It Works

### 1. Market Analysis (Every 5 seconds)

```
Current Price → Fetch OHLC from Binance
              → Calculate ATR (volatility)
              → Detect Trend (EMA crossover)
              → Check Volatility Spike
```

### 2. Grid Generation

**Normal Conditions:**
- Grid spacing = ATR × 0.5
- Buy levels: Below current price at intervals
- TP levels: Above buy levels (spacing × 1.5)

**Strong Uptrend + Volatility Spike:**
- Disable lower (risk) grids
- Keep only top 2 grids (safety)

**Strong Downtrend + Volatility Spike:**
- Pause all buy grids
- Maintain sell (TP) layers only

### 3. Order Placement

- **Buy Orders**: Placed at each active grid level
- **Sell Orders**: Placed at TP targets (symmetrical)
- **Tracking**: Order IDs stored to avoid duplicates
- **Smart Cancellation**: Grids auto-pause during spike events

## GUI Display

### Status Indicators

```
Symbol | Position | Entry Price | Levels | Status
BTC    | 0.5      | 45000       | 5      | ON | UP | VOL↑ | PAUSED
```

| Indicator | Meaning |
|-----------|---------|
| `ON/OFF` | Trading enabled/disabled |
| `UP/DOWN/NEUTRAL` | Current trend |
| `VOL↑` | Volatility spike detected |
| `PAUSED` | Grids disabled (trend + spike) |

## Usage

### Adding a New Trading System

1. Enter **Symbol** (e.g., `BTCNOK`, `ETHUSDT`)
2. Enter **Levels** (e.g., 5 — number of grid levels)
3. Enter **Drawdown%** (legacy field, not used in new strategy)
4. Click **"Add System"**
5. Toggle **ON** to enable trading

### How It Trades

- Grids auto-generate based on real-time ATR
- Buy orders placed below current price
- TP orders placed above entry (risk/reward ratio)
- During volatility spikes: grids pause to avoid whipsaws
- During strong trends: reduces grid density (safety)

### Monitoring

- Watch the **Status** column for `PAUSED` state
- Check console logs (DEBUG level) for grid details
- Use **"Test Firi connection"** to verify API connectivity

## Data Persistence

Grid strategy state is saved in `cryptos.json`:

```json
{
  "BTCNOK": {
    "position": 0.5,
    "entry_price": 45000,
    "num_levels": 5,
    "status": "On",
    "grid_strategy": {...},
    "buy_orders_placed": {1: "order_id_123", ...},
    "sell_orders_placed": {1: "order_id_456", ...}
  }
}
```

## Performance Tips

1. **Start small**: Use 3-5 levels, ~1 BTC/ETH per level
2. **Monitor trends**: Watch for `UP/DOWN` indicators
3. **Adjust levels**: Reduce count if volatility spikes frequently
4. **Use different symbols**: Run grids on multiple pairs for diversification
5. **Check fills**: Verify orders actually filled on Firi (don't assume)

## Limitations & Future Improvements

- ATR calculated from 100 candles (may need more history for stability)
- Trend uses simple EMA (consider MACD or RSI for robustness)
- Volatility spike threshold fixed (could be adaptive per symbol)
- Order quantity hardcoded (should scale with portfolio size)
- No stop-loss (add trailing stop for downside protection)

## Dependencies

- `requests` — Fetch OHLC from Binance, communicate with Firi
- `anthropic` — Portfolio analysis
- `python-dotenv` — Secure API key management

No additional packages required (no talib, numpy, pandas needed).

## Troubleshooting

### "Binance API rate limit exceeded"
- Reduce polling frequency (increase `UPDATE_INTERVAL_MS`)
- Cache OHLC data locally

### "Grid not placing orders"
- Check Firi balance (need cash/crypto)
- Verify Firi API connection with "Test Firi" button
- Check symbol format matches Firi (e.g., `BTCNOK` not `BTC/NOK`)

### "Grids stay paused (VOL↑)"
- Normal during market volatility
- Grid auto-resumes when volatility normalizes
- Can manually toggle system OFF/ON to reset

## Future Enhancements

- [ ] Adaptive grid spacing (scale by daily range)
- [ ] Machine learning trend prediction
- [ ] Portfolio heat mapping
- [ ] Filled order tracking + PnL calculation
- [ ] Risk controls (max drawdown, portfolio allocation %)
- [ ] Multi-symbol correlation analysis
