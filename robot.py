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


# ————— Anthropic Client —————

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
        balances = firi.get_balances()
    except Exception as e:
        logging.exception("Failed to fetch balances from Firi: %s", e)
        return []
    # balances format example (depends on Firi): {"BTC": "0.5", "ETH": "2.0", ...}
    # convert to float
    balances = {sym: float(qty) for sym, qty in balances.items()}

    # 2. Fetch past orders to compute average buy price for each asset
    # We'll fetch **all** filled orders and filter
    try:
        all_orders = firi.list_orders(status="filled")
    except Exception as e:
        logging.exception("Failed to fetch orders from Firi: %s", e)
        all_orders = []
    # all_orders is list of dicts with fields including symbol, side, amount, price, etc.

    # Build a map: symbol -> (total_bought_amount, total_spent)
    stats = {}
    for o in all_orders:
        # Only consider BUY orders (entry)
        if o.get("side") != "buy":
            continue
        sym = o.get("symbol")
        amount = float(o.get("amount", 0))
        # For market orders, "price" may not be set, or there may be average_price
        price = float(o.get("price", o.get("avg_price", 0)))
        cost = amount * price
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
            ticker = firi.get_ticker(sym)
            current_price = float(ticker.get("last", 0))
            unrealized_pl = qty * (current_price - avg_entry)
        else:
            # If no order history, we don't know entry price
            ticker = firi.get_ticker(sym)
            current_price = float(ticker.get("last", 0))

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
    """
    if firi is None:
        return []
    try:
        o = firi.list_orders(status="open")
    except Exception as e:
        logging.exception("Error reading open orders: %s", e)
        return []
    return [
        {
            "symbol": ord.get("symbol"),
            "qty": float(ord.get("amount", 0)),
            "limit_price": float(ord.get("price", 0)) if ord.get("price") else None,
            "side": ord.get("side")
        }
        for ord in o
    ]


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
            self.tree.insert("", "end", values=(
                symbol,
                data.get("position", 0),
                data.get("entry_price", ""),
                str(data.get("levels", "")),
                data.get("status", "Off")
            ))

    def add_crypto(self):
        symbol = self.symbol_entry.get().strip().upper()
        levels = self.levels_entry.get().strip()
        drawdown = self.drawdown_entry.get().strip()

        if not symbol or not levels.isdigit() or not drawdown.replace(".", "", 1).isdigit():
            messagebox.showerror("Error", "Invalid input")
            return

        levels = int(levels)
        drawdown = float(drawdown) / 100.0

        # Placeholder entry price — overwritten later when we compute real buy price
        self.cryptos[symbol] = {
            "position": 0,
            "entry_price": None,
            "levels": {i + 1: None for i in range(levels)},
            "drawdown": drawdown,
            "status": "Off",
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

            # Compute latest entry price (avg buy) and update position
            port = fetch_portfolio()
            # find this symbol in portfolio
            pos = next((p for p in port if p["symbol"] == symbol), None)
            if pos:
                data["position"] = pos["qty"]
                data["entry_price"] = pos["entry_price"]

            # Compute limit order levels from entry price if available
            if data["entry_price"] is not None:
                base_price = data["entry_price"]
                drawdown = data["drawdown"]
                # compute target prices
                new_levels = {}
                for lvl in data["levels"].keys():
                    target_price = round(base_price * (1 - drawdown * lvl), 2)
                    new_levels[lvl] = target_price

                data["levels"] = new_levels

                # Place limit orders if not already open
                for lvl, price in new_levels.items():
                    # check if an order already exists
                    open_orders = fetch_open_orders()
                    exists = any(o["symbol"] == symbol and o["limit_price"] == price for o in open_orders)
                    if not exists:
                        try:
                            firi.submit_order(symbol=symbol, qty=1, side="buy", type_="limit", limit_price=price)
                            changed = True
                        except Exception as e:
                            logging.exception("Error placing order for %s at %s", symbol, price)

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