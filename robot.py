import os
import time
import json
import logging
import hmac
import hashlib
import requests
import threading
import socket
from urllib.parse import urlparse
from collections import deque

import tkinter as tk
from tkinter import ttk, messagebox

from dotenv import load_dotenv
import anthropic

# Load local .env file (if present) into the environment. Do not commit real keys.
# Use an explicit path to avoid `find_dotenv()` issues in interactive shells.
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '.env'))

# ————— Configuration —————

DATA_FILE = "cryptos.json"

# Firi API config
FIRI_API_KEY = os.getenv("FIRI_API_KEY")
FIRI_SECRET_KEY = os.getenv("FIRI_SECRET_KEY")
FIRI_BASE_URL = os.getenv("FIRI_BASE_URL", "https://api.firi.com")
FIRI_CLIENT_ID = os.getenv("FIRI_CLIENT_ID")

# Anthropic config
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

logging.basicConfig(level=logging.INFO)


# ————— Volatility & Trend Analysis —————

class MarketAnalyzer:
    """Fetches OHLC from Binance and computes ATR, EMA, trend."""
    
    BINANCE_BASE = "https://api.binance.com/api/v3"
    
    @staticmethod
    def fetch_ohlc(symbol: str, interval: str = "1h", limit: int = 100):
        """
        Fetch OHLC from Binance.
        symbol: e.g., 'BTCUSDT', 'ETHUSDT'
        interval: '1h', '4h', etc.
        Returns: list of [open_time, open, high, low, close, volume, ...]
        """
        try:
            url = f"{MarketAnalyzer.BINANCE_BASE}/klines"
            params = {
                "symbol": symbol,
                "interval": interval,
                "limit": limit
            }
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logging.error("Failed to fetch OHLC from Binance for %s: %s", symbol, e)
            return []
    
    @staticmethod
    def calculate_atr(ohlc: list, period: int = 14):
        """
        Calculate ATR (Average True Range) from OHLC.
        ohlc: list of [open_time, open, high, low, close, ...]
        Returns: (current_atr, atr_list)
        """
        if len(ohlc) < period:
            return None, []
        
        atr_values = []
        for i in range(len(ohlc)):
            high = float(ohlc[i][2])
            low = float(ohlc[i][3])
            close_curr = float(ohlc[i][4])
            close_prev = float(ohlc[i-1][4]) if i > 0 else close_curr
            
            tr = max(high - low, abs(high - close_prev), abs(low - close_prev))
            atr_values.append(tr)
        
        # Simple moving average of true ranges
        atr = sum(atr_values[-period:]) / period
        return atr, atr_values
    
    @staticmethod
    def calculate_ema(prices: list, period: int = 20):
        """
        Calculate EMA (Exponential Moving Average).
        prices: list of close prices
        Returns: current_ema value
        """
        if len(prices) < period:
            return None
        
        k = 2 / (period + 1)
        ema = sum(prices[:period]) / period
        
        for price in prices[period:]:
            ema = price * k + ema * (1 - k)
        
        return ema
    
    @staticmethod
    def analyze_trend(symbol: str, interval: str = "4h"):
        """
        Detect trend using EMA crossover (20 vs 50).
        Returns: 'up', 'down', or 'neutral'
        """
        ohlc = MarketAnalyzer.fetch_ohlc(symbol, interval=interval, limit=100)
        if not ohlc or len(ohlc) < 50:
            return "neutral"
        
        closes = [float(candle[4]) for candle in ohlc]
        
        ema20 = MarketAnalyzer.calculate_ema(closes, period=20)
        ema50 = MarketAnalyzer.calculate_ema(closes, period=50)
        
        if ema20 is None or ema50 is None:
            return "neutral"
        
        if ema20 > ema50 * 1.01:  # 1% threshold to avoid noise
            return "up"
        elif ema20 < ema50 * 0.99:
            return "down"
        else:
            return "neutral"
    
    @staticmethod
    def is_volatility_spike(symbol: str, interval: str = "1h", threshold_mult: float = 1.5):
        """
        Detect volatility spike: current ATR > threshold_mult × average ATR.
        Returns: bool
        """
        ohlc = MarketAnalyzer.fetch_ohlc(symbol, interval=interval, limit=100)
        if not ohlc or len(ohlc) < 14:
            return False
        
        atr, atr_values = MarketAnalyzer.calculate_atr(ohlc, period=14)
        if atr is None or len(atr_values) < 30:
            return False
        
        avg_atr = sum(atr_values[-30:]) / 30
        current_atr = atr_values[-1]
        
        return current_atr > avg_atr * threshold_mult


# ————— Firi REST Client —————

class FiriClient:
    def __init__(self, api_key: str, secret_key: str, base_url: str = "https://api.firi.com"):
        if not api_key or not secret_key:
            raise ValueError("Firi API key or secret key not provided")
        self.api_key = api_key
        self.secret_key = secret_key
        self.client_id = os.getenv("FIRI_CLIENT_ID")
        self.base_url = base_url.rstrip("/")
        
    def _generate_signature(self, body_dict: dict):
        """
        Generate HMAC-SHA256 signature for Firi API.
        The signature is calculated from a JSON object containing timestamp, validity, and request parameters.
        """
        # Create compact JSON (no whitespace) - this is what gets signed
        message = json.dumps(body_dict, separators=(',', ':'))
        
        signature = hmac.new(
            self.secret_key.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()
        return signature
    
    def _get_auth_params(self, request_body: dict = None):
        """
        Generate authentication parameters for Firi API.
        Returns tuple of (url_params, headers, body_to_send)
        """
        # Timestamp in seconds since epoch (as string)
        timestamp = str(int(time.time()))
        # Validity period in milliseconds (as string)
        validity = "2000"
        
        # Build the body dict for signing (includes timestamp and validity)
        sign_body = {
            "timestamp": timestamp,
            "validity": validity
        }
        
        # Add request parameters if present
        if request_body:
            sign_body.update(request_body)
        
        # Generate signature from the full body
        signature = self._generate_signature(sign_body)
        
        # URL parameters (timestamp and validity required in URL too)
        url_params = f"?timestamp={timestamp}&validity={validity}"
        
        # Headers - use correct Firi header names
        headers = {
            "Content-Type": "application/json",
            "miraiex-user-signature": signature,
            "miraiex-user-clientid": self.client_id
        }
        
        return url_params, headers, request_body if request_body else {}

    def _request(self, method: str, path: str, body: dict = None):
        # Get authentication parameters
        url_params, headers, body_to_send = self._get_auth_params(body)
        
        # Construct full URL
        url = f"{self.base_url}{path}{url_params}"
        
        logging.debug("FIRI REQUEST: %s %s", method, path)
        logging.debug("URL: %s", url)
        
        try:
            if body_to_send:
                resp = requests.request(method, url, headers=headers, json=body_to_send)
            else:
                resp = requests.request(method, url, headers=headers)
                
            logging.debug("Response status: %s", resp.status_code)
            
            resp.raise_for_status()
            return resp.json()
            
        except requests.exceptions.HTTPError as e:
            logging.error("Firi API HTTP error %s: %s", e.response.status_code, e.response.text)
            raise Exception(f"Firi API error {e.response.status_code}: {e.response.text}")
        except requests.exceptions.RequestException as e:
            logging.error("Firi API request error: %s", e)
            raise

    def get_balances(self):
        return self._request("GET", "/v2/balances")

    def list_orders(self, symbol: str = None, status: str = None):
        """
        Get orders.
        status: 'open' for active orders, 'filled'/'closed' for history
        symbol: market name like 'BTCNOK'
        """
        if status in ("filled", "closed"):
            if symbol:
                return self._request("GET", f"/v2/orders/{symbol}/history")
            return self._request("GET", "/v2/orders/history")
        else:
            # Active orders
            if symbol:
                return self._request("GET", f"/v2/orders/{symbol}")
            return self._request("GET", "/v2/orders")

    def submit_order(self, symbol: str, qty: float, side: str, type_: str = "limit", limit_price: float = None):
        """
        Submit an order.
        symbol: market like 'BTCNOK'
        qty: amount to buy/sell
        side: 'buy' or 'sell'
        type_: 'limit' (Firi requires limit orders)
        limit_price: price for limit orders
        """
        if type_ != "limit" or limit_price is None:
            raise ValueError("Firi requires limit orders with a price")
            
        body = {
            "market": symbol,
            "type": "bid" if side == "buy" else "ask",
            "amount": str(qty),
            "price": str(limit_price)
        }
        
        return self._request("POST", "/v2/orders", body)

    def get_ticker(self, symbol: str):
        return self._request("GET", f"/v2/markets/{symbol}/ticker")
        
    def get_markets(self):
        """Get list of available markets"""
        return self._request("GET", "/v2/markets")


# ————— Enhanced Dynamic Grid Strategy —————

class GridStrategy:
    """
    Dynamic grid strategy with ATR-based spacing, trend filtering, and symmetrical TP.
    """
    
    def __init__(self, symbol: str, base_price: float, num_levels: int = 5):
        """
        Initialize grid strategy.
        symbol: trading pair (e.g., 'BTCNOK')
        base_price: current market price to build grid around
        num_levels: number of grid levels (default 5)
        """
        self.symbol = symbol
        self.base_price = base_price
        self.num_levels = num_levels
        self.buy_levels = {}
        self.sell_levels = {}
        self.trend = "neutral"
        self.volatility_spike = False
        self.atr = None
        self.grid_active = True
        
    def update_market_conditions(self):
        """Fetch ATR and trend, update strategy state."""
        # Get Binance symbol (convert from Firi format if needed)
        binance_symbol = self._to_binance_symbol(self.symbol)
        
        # Analyze trend (4h)
        self.trend = MarketAnalyzer.analyze_trend(binance_symbol, interval="4h")
        
        # Check volatility spike (1h)
        self.volatility_spike = MarketAnalyzer.is_volatility_spike(
            binance_symbol, interval="1h", threshold_mult=1.5
        )
        
        # Get ATR for grid spacing
        ohlc = MarketAnalyzer.fetch_ohlc(binance_symbol, interval="1h", limit=100)
        if ohlc and len(ohlc) >= 14:
            self.atr, _ = MarketAnalyzer.calculate_atr(ohlc, period=14)
        
        # Disable grids if strong trend + volatility spike
        self.grid_active = not (self.trend in ("up", "down") and self.volatility_spike)
    
    def _to_binance_symbol(self, firi_symbol: str):
        """Convert Firi symbol (e.g., 'BTCNOK') to Binance (e.g., 'BTCUSDT')."""
        # Simplified mapping — adjust based on actual Firi/Binance symbols
        symbol_map = {
            "BTCNOK": "BTCUSDT",
            "ETHNOK": "ETHUSDT",
            "ADANOK": "ADAUSDT",
            "AVAXNOK": "AVAXUSDT",
        }
        return symbol_map.get(firi_symbol, firi_symbol.replace("NOK", "USDT"))
    
    def generate_grids(self):
        """
        Generate buy and sell grids based on ATR and trend.
        Grid spacing = ATR * 0.5
        TP target = Grid spacing * 1.5
        """
        if self.atr is None or self.atr <= 0:
            # Fallback: use 2% if ATR unavailable
            grid_spacing = self.base_price * 0.02
        else:
            grid_spacing = self.atr * 0.5
        
        tp_target = grid_spacing * 1.5
        
        self.buy_levels = {}
        self.sell_levels = {}
        
        for i in range(1, self.num_levels + 1):
            # Buy levels: below base price
            buy_price = round(self.base_price - (grid_spacing * i), 2)
            self.buy_levels[i] = buy_price
            
            # Sell levels (TP): symmetrical above buy level + target
            sell_price = round(buy_price + tp_target, 2)
            self.sell_levels[i] = sell_price
        
        # If strong trend + volatility spike, disable lower (risk) grids
        if not self.grid_active and self.trend == "up":
            # Keep only top 2 grids during strong up trend
            self.buy_levels = {k: v for k, v in self.buy_levels.items() if k <= 2}
            self.sell_levels = {k: v for k, v in self.sell_levels.items() if k <= 2}
        elif not self.grid_active and self.trend == "down":
            # During strong down trend, disable buy grids entirely
            self.buy_levels = {}
            self.sell_levels = {}
    
    def get_buy_orders(self):
        """Return list of buy orders to place."""
        if not self.grid_active:
            return []
        return [{"price": price, "level": lvl} for lvl, price in self.buy_levels.items()]
    
    def get_sell_orders(self):
        """Return list of sell (TP) orders to place."""
        if not self.grid_active:
            return []
        return [{"price": price, "level": lvl} for lvl, price in self.sell_levels.items()]
    
    def get_status(self):
        """Return human-readable status."""
        status = {
            "trend": self.trend,
            "volatility_spike": self.volatility_spike,
            "grid_active": self.grid_active,
            "atr": round(self.atr, 2) if self.atr else None,
            "buy_levels": self.buy_levels,
            "sell_levels": self.sell_levels,
        }
        return status



anthropic_client = None
if ANTHROPIC_API_KEY:
    anthropic_client = anthropic.Client(api_key=ANTHROPIC_API_KEY)
else:
    logging.warning("Anthropic API key not set — AI disabled.")


# ————— Helper Functions —————

def fetch_portfolio():
    """
    Build a portfolio representation based on Firi balances
    and past filled buy orders to compute average entry price.
    """
    if firi is None:
        return []

    # 1. Fetch balances
    try:
        balances_list = firi.get_balances()
    except Exception as e:
        logging.exception("Failed to fetch balances from Firi: %s", e)
        return []
    
    # balances_list is a list of dicts: [{"currency": "BTC", "balance": "0.5", "available": "0.4", ...}]
    # Convert to dict: {"BTC": 0.5, "ETH": 2.0, ...}
    if not isinstance(balances_list, list):
        logging.error("Unexpected balances format: %s", type(balances_list))
        return []
    
    balances = {}
    for item in balances_list:
        currency = item.get("currency")
        balance = float(item.get("balance", 0))
        if currency and balance > 0:
            balances[currency] = balance

    # 2. Fetch past orders to compute average buy price for each asset
    # We'll fetch **all** filled orders and filter
    try:
        all_orders = firi.list_orders(status="filled")
    except Exception as e:
        logging.exception("Failed to fetch orders from Firi: %s", e)
        all_orders = []
    
    if not isinstance(all_orders, list):
        all_orders = []
    
    # all_orders is list of dicts with fields including symbol, side, amount, price, etc.

    # Build a map: symbol -> (total_bought_amount, total_spent)
    stats = {}
    for o in all_orders:
        # Only consider BUY orders (entry)
        side = o.get("side")
        # Firi uses "bid" for buy, "ask" for sell
        if side not in ("buy", "bid"):
            continue
        
        sym = o.get("market") or o.get("symbol")  # Try both field names
        amount = float(o.get("amount", 0))
        # For market orders, "price" may not be set, or there may be average_price
        price = float(o.get("price", o.get("avg_price", 0)))
        cost = amount * price
        
        if sym and cost > 0:
            if sym not in stats:
                stats[sym] = {"amt": 0.0, "cost": 0.0}
            stats[sym]["amt"] += amount
            stats[sym]["cost"] += cost

    portfolio = []
    for sym, qty in balances.items():
        if qty <= 0:
            continue

        avg_entry = None
        unrealized_pl = None
        current_price = None
        side = "buy"

        if sym in stats and stats[sym]["amt"] > 0:
            avg_entry = stats[sym]["cost"] / stats[sym]["amt"]
            # fetch latest market price
            try:
                ticker = firi.get_ticker(sym)
                current_price = float(ticker.get("last", 0))
                unrealized_pl = qty * (current_price - avg_entry)
            except Exception as e:
                logging.debug("Could not fetch ticker for %s: %s", sym, e)
        else:
            # If no order history, we don't know entry price
            try:
                ticker = firi.get_ticker(sym)
                current_price = float(ticker.get("last", 0))
            except Exception as e:
                logging.debug("Could not fetch ticker for %s: %s", sym, e)

        portfolio.append({
            "symbol": sym,
            "qty": qty,
            "entry_price": avg_entry,
            "current_price": current_price,
            "unrealized_pl": unrealized_pl,
            "side": side
        })

    return portfolio


def fetch_open_orders():
    """
    Fetch open orders from Firi.
    Returns list of dicts with symbol, qty, limit_price, side
    """
    if firi is None:
        return []
    try:
        orders = firi.list_orders(status="open")
    except Exception as e:
        logging.exception("Error reading open orders: %s", e)
        return []
    
    if not isinstance(orders, list):
        return []
    
    result = []
    for ord in orders:
        symbol = ord.get("market") or ord.get("symbol")
        qty = float(ord.get("amount", 0))
        price = float(ord.get("price", 0)) if ord.get("price") else None
        side = ord.get("side")
        # Convert "bid" -> "buy", "ask" -> "sell" for consistency
        if side == "bid":
            side = "buy"
        elif side == "ask":
            side = "sell"
        
        if symbol and qty > 0:
            result.append({
                "symbol": symbol,
                "qty": qty,
                "limit_price": price,
                "side": side
            })
    
    return result


def ai_analysis(message: str):
    """
    Ask Claude (Anthropic) for portfolio analysis + context + question.
    """
    if anthropic_client is None:
        return "AI not configured (Anthropic API key missing)."

    portfolio = fetch_portfolio()
    open_orders = fetch_open_orders()

    prompt = (
        "You are an AI portfolio manager responsible for analyzing my crypto-portfolio.\n"
        "Here is my current portfolio (symbol, qty, entry price, current price, unrealized P/L):\n"
        f"{portfolio}\n\n"
        "Here are my open orders:\n"
        f"{open_orders}\n\n"
        "Tasks:\n"
        "1. Evaluate risk exposures.\n"
        "2. Analyze the open limit orders and their potential impact.\n"
        "3. Provide insights into portfolio health and diversification.\n"
        "4. Speculate on the market outlook.\n"
        "5. Identify potential risks and suggest risk management strategies.\n\n"
        f"User question: {message}\n"
    )

    try:
        resp = anthropic_client.completions.create(
            model="claude-2.1",
            prompt=prompt,
            max_tokens_to_sample=512
        )
    except Exception as e:
        logging.exception("Anthropic completion error")
        return f"AI error: {e}"

    # Handle different resp types
    if isinstance(resp, dict):
        return resp.get("completion") or resp.get("text") or str(resp)
    else:
        return getattr(resp, "completion", None) or getattr(resp, "text", None) or str(resp)


# ————— GUI / Bot Logic —————

class TradingBotGUI:
    UPDATE_INTERVAL_MS = 5_000

    def __init__(self, root):
        self.root = root
        self.root.title("Trading Bot")
        self.cryptos = self.load_cryptos()

        # GUI: form
        self.form_frame = tk.Frame(root)
        self.form_frame.pack(pady=10)

        tk.Label(self.form_frame, text="Symbol:").grid(row=0, column=0)
        self.symbol_entry = tk.Entry(self.form_frame)
        self.symbol_entry.grid(row=0, column=1)

        tk.Label(self.form_frame, text="Levels:").grid(row=0, column=2)
        self.levels_entry = tk.Entry(self.form_frame)
        self.levels_entry.grid(row=0, column=3)

        tk.Label(self.form_frame, text="Drawdown%:").grid(row=0, column=4)
        self.drawdown_entry = tk.Entry(self.form_frame)
        self.drawdown_entry.grid(row=0, column=5)

        self.add_button = tk.Button(self.form_frame, text="Add crypto", command=self.add_crypto)
        self.add_button.grid(row=0, column=6)

        # GUI: table
        self.tree = ttk.Treeview(root, columns=("Symbol", "Position", "Entry Price", "Levels", "Status"), show="headings")
        for col in ("Symbol", "Position", "Entry Price", "Levels", "Status"):
            self.tree.heading(col, text=col)
            self.tree.column(col, width=120)
        self.tree.pack(pady=10)

        # Toggle / remove
        self.toggle_system_button = tk.Button(root, text="Toggle Selected System", command=self.toggle_selected_system)
        self.toggle_system_button.pack(pady=5)

        self.remove_button = tk.Button(root, text="Remove Selected crypto", command=self.remove_selected_crypto)
        self.remove_button.pack(pady=5)

        # Chat / AI
        self.chat_frame = tk.Frame(root)
        self.chat_frame.pack(pady=10)

        self.chat_input = tk.Entry(self.chat_frame, width=50)
        self.chat_input.grid(row=0, column=0, padx=5)
        self.send_button = tk.Button(self.chat_frame, text="Send", command=self.send_message)
        self.send_button.grid(row=0, column=1)

        self.chat_output = tk.Text(root, height=8, width=80, state=tk.DISABLED)
        self.chat_output.pack()

        # Firi test
        self.test_button = tk.Button(root, text="Test Firi connection", command=self.test_firi_connection)
        self.test_button.pack(pady=5)

        self.refresh_table()

        self._after_id = None
        self.schedule_periodic_update()

        if firi is None:
            messagebox.showwarning("Firi Not Configured", "Firi API keys missing — trading disabled.")

    # — Data persistence
    def save_cryptos(self):
        with open(DATA_FILE, "w") as f:
            json.dump(self.cryptos, f, indent=2)

    def load_cryptos(self):
        try:
            with open(DATA_FILE, "r") as f:
                data = json.load(f)
            return data
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    # — GUI actions
    def refresh_table(self):
        for row in self.tree.get_children():
            self.tree.delete(row)

        for symbol, data in self.cryptos.items():
            grid = data.get("grid_strategy")
            
            # Determine grid status
            if grid:
                status_text = f"{'ON' if data.get('status') == 'On' else 'Off'} | {grid.trend.upper()}"
                if grid.volatility_spike:
                    status_text += " | VOL↑"
                if not grid.grid_active:
                    status_text += " | PAUSED"
            else:
                status_text = data.get("status", "Off")
            
            self.tree.insert("", "end", values=(
                symbol,
                data.get("position", 0),
                data.get("entry_price", ""),
                str(data.get("num_levels", "")),
                status_text
            ))

    def add_crypto(self):
        symbol = self.symbol_entry.get().strip().upper()
        levels = self.levels_entry.get().strip()
        drawdown = self.drawdown_entry.get().strip()

        if not symbol or not levels.isdigit() or not drawdown.replace(".", "", 1).isdigit():
            messagebox.showerror("Error", "Invalid input")
            return

        num_levels = int(levels)
        # drawdown is now just a UI field for backwards compatibility, but not used in grid

        # Store grid strategy config
        self.cryptos[symbol] = {
            "position": 0,
            "entry_price": None,
            "num_levels": num_levels,
            "status": "Off",
            "grid_strategy": None,  # Will be initialized on first trade_systems() call
            "buy_orders_placed": {},  # Track placed order IDs
            "sell_orders_placed": {},  # Track placed order IDs
        }
        self.save_cryptos()
        self.refresh_table()

    def toggle_selected_system(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showerror("Error", "No crypto selected")
            return
        for item in sel:
            symbol = self.tree.item(item)["values"][0]
            cur = self.cryptos[symbol].get("status", "Off")
            self.cryptos[symbol]["status"] = "On" if cur == "Off" else "Off"
        self.save_cryptos()
        self.refresh_table()

    def remove_selected_crypto(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("Warning", "No crypto selected")
            return
        for item in sel:
            symbol = self.tree.item(item)["values"][0]
            self.cryptos.pop(symbol, None)
        self.save_cryptos()
        self.refresh_table()

    def send_message(self):
        msg = self.chat_input.get().strip()
        if not msg:
            return
        resp = ai_analysis(msg)
        self.chat_output.config(state=tk.NORMAL)
        self.chat_output.insert(tk.END, f"You: {msg}\n{resp}\n\n")
        self.chat_output.config(state=tk.DISABLED)
        self.chat_input.delete(0, tk.END)

    # — Trading logic
    def trade_systems(self):
        if firi is None:
            return

        changed = False

        for symbol, data in self.cryptos.items():
            if data.get("status") != "On":
                continue

            # Fetch current portfolio position
            port = fetch_portfolio()
            pos = next((p for p in port if p["symbol"] == symbol), None)
            
            if pos:
                data["position"] = pos["qty"]
                data["entry_price"] = pos["entry_price"]
                current_price = pos["current_price"]
            else:
                current_price = None
                # Try to fetch current price from Firi ticker
                try:
                    ticker = firi.get_ticker(symbol)
                    current_price = float(ticker.get("last", 0))
                except Exception as e:
                    logging.debug("Could not fetch price for %s: %s", symbol, e)
                    current_price = None
            
            if current_price is None or current_price <= 0:
                logging.warning("Skipping %s — invalid price", symbol)
                continue
            
            # Initialize or update grid strategy
            if data.get("grid_strategy") is None:
                grid = GridStrategy(symbol, current_price, num_levels=data.get("num_levels", 5))
                data["grid_strategy"] = grid
            else:
                grid = data["grid_strategy"]
                # Update base price
                grid.base_price = current_price
            
            # Update market conditions (trend, ATR, volatility)
            try:
                grid.update_market_conditions()
            except Exception as e:
                logging.debug("Error updating market conditions for %s: %s", symbol, e)
                # Continue with previous conditions
            
            # Generate grids
            grid.generate_grids()
            
            # Place buy orders if grid is active
            buy_orders = grid.get_buy_orders()
            for order in buy_orders:
                lvl = order["level"]
                price = order["price"]
                
                # Check if order already placed
                existing = data.get("buy_orders_placed", {})
                if lvl in existing:
                    continue  # Already placed
                
                try:
                    result = firi.submit_order(
                        symbol=symbol,
                        qty=1.0,  # Adjust based on your strategy
                        side="buy",
                        type_="limit",
                        limit_price=price
                    )
                    data["buy_orders_placed"][lvl] = result.get("id", str(lvl))
                    logging.info("Placed BUY order for %s at level %d (price %.2f)", symbol, lvl, price)
                    changed = True
                except Exception as e:
                    logging.error("Error placing BUY order for %s at level %d: %s", symbol, lvl, e)
            
            # Place sell orders (TP) if grid is active
            sell_orders = grid.get_sell_orders()
            for order in sell_orders:
                lvl = order["level"]
                price = order["price"]
                
                # Check if order already placed
                existing = data.get("sell_orders_placed", {})
                if lvl in existing:
                    continue  # Already placed
                
                try:
                    result = firi.submit_order(
                        symbol=symbol,
                        qty=1.0,  # Adjust based on your strategy
                        side="sell",
                        type_="limit",
                        limit_price=price
                    )
                    data["sell_orders_placed"][lvl] = result.get("id", str(lvl))
                    logging.info("Placed SELL (TP) order for %s at level %d (price %.2f)", symbol, lvl, price)
                    changed = True
                except Exception as e:
                    logging.error("Error placing SELL order for %s at level %d: %s", symbol, lvl, e)
        
        if changed:
            self.save_cryptos()
            self.refresh_table()

    # — Scheduling
    def schedule_periodic_update(self):
        try:
            self.trade_systems()
        except Exception:
            logging.exception("Error in trade loop")
        self._after_id = self.root.after(self.UPDATE_INTERVAL_MS, self.schedule_periodic_update)

    def stop_periodic_update(self):
        if self._after_id:
            self.root.after_cancel(self._after_id)
            self._after_id = None

    # — Test Firi connection
    def test_firi_connection(self):
        if firi is None:
            messagebox.showwarning("Firi Not Configured", "Firi API keys missing or invalid.")
            return

        try:
            balances = firi.get_balances()
            open_orders = firi.list_orders(status="open")
            messagebox.showinfo("Firi Test", f"Balances: {balances}\nOpen orders: {open_orders}")
        except Exception as e:
            messagebox.showerror("Firi Error", f"Error calling Firi API: {e}")

    def on_close(self):
        self.stop_periodic_update()
        self.save_cryptos()
        self.root.destroy()


# ————— Entry Point —————

if __name__ == "__main__":
    # Initialize Firi client
    try:
        firi = FiriClient(FIRI_API_KEY, FIRI_SECRET_KEY, FIRI_BASE_URL)
    except Exception as e:
        logging.exception("Failed to create Firi client")
        firi = None

    root = tk.Tk()
    app = TradingBotGUI(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()