# Trading Bot - Production-Ready Crypto Grid Trading System

A sophisticated, modular cryptocurrency trading bot with advanced risk management, order lifecycle tracking, and real-time volatility-aware grid optimization.

## Architecture Overview

### Core Modules

1. **risk_manager.py** — Safety & risk controls
   - Global kill-switch to halt trading
   - Per-symbol capital allocation limits
   - Portfolio-level exposure ceilings
   - Pre-trade validations (spread, slippage, minimum order size)
   - Circuit breakers for extreme volatility
   - Dry-run mode for testing

2. **order_lifecycle.py** — Order tracking & management
   - Order status polling from Firi
   - Fill detection and TP order placement
   - Automatic expiry handling
   - Grid level tracking
   - Recovery from bot restarts

3. **logger.py** — Structured logging
   - JSON-formatted logs with timestamps
   - Order placement/fill events logged
   - Grid generation events
   - Risk validation audit trail
   - Log export to JSON file

4. **persistence.py** — State recovery
   - Save/restore bot operational state
   - Per-symbol grid configuration persistence
   - Open order snapshots
   - Recovery on bot restart

5. **api_resilience.py** — Robust API communication
   - Exponential backoff retry logic
   - Connection/timeout handling
   - Session management
   - Configurable retry attempts

6. **robot.py** (main) — Orchestration
   - Firi API client with HMAC authentication
   - Market analyzer (ATR, EMA, trend detection)
   - Grid strategy generator
   - Tkinter GUI
   - Periodic trading loop

---

## Getting Started

### Installation

```bash
# Clone repository
git clone https://github.com/Benjamin0806/Trader_robot.git
cd Trader_robot

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Configuration

1. **Create `.env` file** (don't commit this):
```bash
FIRI_API_KEY=your_api_key
FIRI_SECRET_KEY=your_secret_key
FIRI_CLIENT_ID=your_client_id
FIRI_BASE_URL=https://api.firi.com
ANTHROPIC_API_KEY=your_anthropic_key
```

2. **Optional: Create `config.json`** for risk parameters:
```json
{
  "risk": {
    "trading_enabled": true,
    "max_capital_per_symbol": 0.20,
    "max_total_exposure": 0.80,
    "min_spread_pct": 0.05,
    "atr_spike_circuit_breaker": 0.30,
    "dry_run": false,
    "min_order_value": 100.0
  },
  "grid": {
    "default_levels": 5,
    "atr_period": 14,
    "grid_spacing_multiplier": 0.5,
    "tp_multiplier": 1.5
  }
}
```

### Running the Bot

```bash
source .venv/bin/activate
python3 robot.py
```

The GUI will launch with:
- **Market tab** — Add/manage trading systems
- **Risk tab** — Kill-switch, exposure limits, dry-run toggle
- **Orders tab** — View open orders and fills
- **Grid tab** — Visual grid levels and status
- **Logs tab** — Real-time log viewer
- **AI Chat** — Portfolio analysis with Claude

---

## Usage

### Adding a Trading System

1. Open the app
2. Go to **Market** tab
3. Enter:
   - **Symbol**: `BTCNOK` (Firi market name)
   - **Levels**: `5` (number of grid levels)
   - **Drawdown%**: `5` (legacy field, ignored)
4. Click **"Add System"**
5. Toggle **ON** to enable

### Safety Features

#### Kill Switch
- Located in **Risk** tab
- Stops all new order placement immediately
- **Does NOT cancel existing orders** (for safety)

#### Dry-Run Mode
- Toggle in **Risk** tab
- Orders are logged but not submitted to Firi
- Perfect for testing strategy without real capital

#### Exposure Limits
```python
max_capital_per_symbol = 0.20  # Max 20% of portfolio per symbol
max_total_exposure = 0.80      # Max 80% total portfolio exposure
```

#### Pre-Trade Validations
- Minimum spread check (avoid placing during wide spreads)
- Minimum order value validation
- Slippage protection
- Price deviation checks

#### Circuit Breaker
- Pauses grids if ATR changes >30% in one candle
- Auto-resumes when volatility normalizes

### Monitoring

#### Logs
- **Real-time logs** in GUI log viewer
- **JSON logs** in `logs/trading_YYYYMMDD_HHMMSS.jsonl`
- Export logs via **"Export Logs"** button

#### Order Tracking
- **Orders tab** shows all open/filled orders
- Color-coded by status (green=filled, yellow=open, red=failed)
- Click to view order details

#### Grid Status
- **Status column** shows: `ON | UP | VOL↑ | PAUSED`
  - `ON/OFF` — Trading enabled/disabled
  - `UP/DOWN/NEUTRAL` — Current trend
  - `VOL↑` — Volatility spike detected
  - `PAUSED` — Grid paused (risk/trend condition)

---

## Data Files

```
.
├── .env                    # API keys (git-ignored)
├── cryptos.json           # Trading systems (GUI state)
├── state/
│   ├── bot_state.json     # Operational state
│   ├── grid_config.json   # Per-symbol config
│   └── open_orders.json   # Order snapshots
└── logs/
    └── trading_*.jsonl    # Structured JSON logs
```

---

## API Reference

### RiskManager

```python
from risk_manager import RiskManager, RiskConfig

config = RiskConfig(
    max_capital_per_symbol=0.20,
    max_total_exposure=0.80,
    dry_run=False
)
risk_mgr = RiskManager(config)

# Check if we can trade
can_trade, reason = risk_mgr.can_trade_symbol("BTCNOK", position_value=10000)

# Validate order
valid, reason = risk_mgr.validate_order("BTCNOK", qty=1.0, price=50000, side="buy")

# Check circuit breaker
passed, reason = risk_mgr.check_circuit_breaker(current_atr=500, previous_atr=400)

# Toggle kill-switch
risk_mgr.set_trading_enabled(False)
```

### OrderLifecycleManager

```python
from order_lifecycle import OrderLifecycleManager, Order

order_mgr = OrderLifecycleManager(firi_client)

# Register order
order = Order(order_id="12345", symbol="BTCNOK", side="buy", qty=1.0, price=50000)
order_mgr.register_order(order)

# Poll for updates
filled_orders = order_mgr.poll_all_orders()

# Mark as filled
order_mgr.mark_filled("12345", filled_qty=1.0)

# Get status
status = order_mgr.get_status()
print(status)
```

### StructuredLogger

```python
from logger import get_logger

logger = get_logger()

# Log order events
logger.log_order_placed("BTCNOK", "buy", qty=1.0, price=50000, order_id="123")
logger.log_order_filled("BTCNOK", "buy", qty=1.0, price=50000, order_id="123")

# Log grid events
logger.log_grid_generated(
    symbol="BTCNOK",
    trend="up",
    atr=500,
    buy_levels={1: 49500, 2: 49000},
    sell_levels={1: 50500, 2: 51000}
)

# Export logs
logger.export_logs("export.json")
```

### PersistenceManager

```python
from persistence import get_persistence_manager, GridConfig

persistence = get_persistence_manager()

# Save state
state = {"balance": 10000, "last_update": "2025-01-01"}
persistence.save_bot_state(state)

# Load state
loaded_state = persistence.load_bot_state()

# Manage grid configs
configs = {
    "BTCNOK": GridConfig(symbol="BTCNOK", num_levels=5, enabled=True)
}
persistence.save_grid_configs(configs)
```

---

## Advanced Configuration

### Per-Symbol Grid Settings

Edit `state/grid_config.json`:
```json
{
  "BTCNOK": {
    "symbol": "BTCNOK",
    "num_levels": 5,
    "enabled": true
  },
  "ETHUSDT": {
    "symbol": "ETHUSDT",
    "num_levels": 7,
    "enabled": false
  }
}
```

### API Resilience

Customize retry behavior in code:
```python
from api_resilience import RetryConfig, exponential_backoff_retry

config = RetryConfig(
    max_retries=5,
    base_delay=0.5,
    max_delay=60.0,
    backoff_factor=2.0,
    timeout=15
)

# Use with any function
result = exponential_backoff_retry(my_api_call, config)
```

---

## Troubleshooting

### Bot Won't Start
1. Check `.env` file exists and has all keys
2. Verify `python3 -m robot` works
3. Check logs: `tail logs/trading_*.jsonl`

### Orders Not Placing
1. Check kill-switch is enabled
2. Verify dry-run mode is OFF
3. Check risk limits (exposure, per-symbol allocation)
4. Verify Firi has sufficient balance
5. Check "Test Firi connection" button

### Grid Paused (VOL↑)
- Normal during market spikes
- Grid auto-resumes when volatility normalizes
- Can manually toggle system OFF/ON to reset

### Logs Not Updating
- Check `logs/` directory has write permissions
- Verify log file is not corrupted: `ls -lh logs/`

---

## Best Practices

### Risk Management
1. **Start with dry-run**: Test strategy without real capital
2. **Use conservative limits**: Start with 10-20% per symbol
3. **Monitor trends**: Watch for `DOWN` trend before heavy trading
4. **Set reasonable grid levels**: 3-7 levels usually sufficient
5. **Avoid wide spreads**: Use `min_spread_pct` check

### Operations
1. **Check logs daily**: Review order fills and any errors
2. **Monitor exposure**: Keep total below 80%
3. **Rebalance regularly**: Adjust positions to stay within limits
4. **Use kill-switch liberally**: Don't hesitate to pause trading
5. **Export logs weekly**: Archive for analysis

### Strategy Tuning
1. **ATR-based grids**: Automatically adapt to volatility
2. **Trend filtering**: Reduces losses in strong trends
3. **TP symmetry**: Ensures consistent risk/reward
4. **Dry-run testing**: Test new settings risk-free

---

## Performance Considerations

- **Update interval**: 5 seconds (can adjust in code)
- **API calls**: ~2-3 per cycle (Binance OHLC, Firi orders/balances)
- **Log growth**: ~1MB per 1000 orders
- **Memory**: ~50-100MB typical

---

## Future Enhancements

- [ ] WebSocket support for real-time price updates
- [ ] Machine learning trend prediction
- [ ] Multi-exchange support (Binance, Kraken, etc.)
- [ ] Telegram/Discord notifications
- [ ] REST API for remote control
- [ ] Historical backtest engine
- [ ] Advanced order types (stop-loss, trailing stop)
- [ ] Portfolio heat mapping
- [ ] Tax report generation

---

## License

MIT License - See LICENSE file

## Support

Issues? Questions? Open an issue on GitHub or email: [contact]

---

**Last Updated**: 2025-11-20
**Version**: 2.0 (Production-Ready)
