import tkinter as tk
from tkinter import ttk, messagebox
import json
import time
import threading
import random
import os
import logging
import inspect
import anthropic
import firipy

DATA_FILE = 'cryptos.json'

# Read API keys from environment variables (do NOT hard-code keys in source)
API_KEY_FIRI = os.getenv("FIRI_API_KEY")
SECRET_KEY_FIRI = os.getenv("FIRI_SECRET_KEY")
BASE_URL = os.getenv("FIRI_BASE_URL", "https://api.firi.no")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

logging.basicConfig(level=logging.INFO)


def create_firi_client(api_key, secret, base_url):
    if not api_key or not secret:
        logging.warning("Firi API key/secret not set. Firi client will be disabled.")
        return None
    # firipy exposes different client interfaces depending on version.
    # We'll attempt to call constructors using only the keyword args they accept.
    def try_call(constructor, available_kwargs):
        try:
            sig = inspect.signature(constructor)
            # build kwargs only with parameters the constructor accepts
            call_kwargs = {}
            for name, param in sig.parameters.items():
                if name == 'self':
                    continue
                if name in available_kwargs:
                    call_kwargs[name] = available_kwargs[name]
            return constructor(**call_kwargs)
        except Exception:
            return None

    available = {
        'api_key': api_key,
        'key': api_key,
        'secret': secret,
        'secret_key': secret,
        'base_url': base_url,
        'host': base_url,
        'api_version': 'v2',
    }

    # Try common constructors in order of likelihood
    if hasattr(firipy, 'REST'):
        client = try_call(getattr(firipy, 'REST'), available)
        if client:
            return client
    if hasattr(firipy, 'FiriAPI'):
        client = try_call(getattr(firipy, 'FiriAPI'), available)
        if client:
            return client
    if hasattr(firipy, 'Client'):
        client = try_call(getattr(firipy, 'Client'), available)
        if client:
            return client

    logging.error("Unable to instantiate firipy client; please check firipy version and API.")
    return None


# Instantiate clients
api = create_firi_client(API_KEY_FIRI, SECRET_KEY_FIRI, BASE_URL)
anthropic_client = None
if not ANTHROPIC_API_KEY:
    logging.warning("Anthropic API key not set. Anthropic calls will be disabled.")
else:
    try:
        anthropic_client = anthropic.Client(api_key=ANTHROPIC_API_KEY)
    except Exception:
        logging.exception("Failed to create Anthropic client. Check the anthropic package and API key.")

def fetch_portfolio():
    positions = api.list_positions()
    portfolio = []
    for position in positions:
        portfolio.append({
            "symbol": position.symbol,
            "qty": position.qty,
            "entry_price": position.avg_entry_price,
            "current_price": position.current_price,
            "unrealized_pl": position.unrealized_pl,
            "side": "buy"
        })
    return portfolio

def fetch_open_orders():
    orders = api.list_orders(status='open')
    open_orders = []
    for order in orders:
        open_orders.append({
            "symbol": order.symbol,
            "qty": order.qty,
            "limit_price": order.limit_price,
            "side": "buy"
        })
    return open_orders

def fetch_mock_api(symbol):
    return {
        "price": 100
    }

def chatgpt_response(message):
    # This function uses the Anthropic client (Claude). If the client is not
    # configured, return an informative message.
    if anthropic_client is None:
        return "Anthropic API key not configured. Set ANTHROPIC_API_KEY in your environment."

    portfolio_data = fetch_portfolio()
    open_orders = fetch_open_orders()

    pre_prompt = (
        "You are an AI portfolio manager responsible for analyzing my crypto-portfolio.\n"
        "Your tasks are the following:\n"
        "1. Evaluate risk-exposures of my current holdings.\n"
        "2. Analyze my open limit orders and their potential impact.\n"
        "3. Provide insights into portfolio health, diversification, trade-adjustments etc.\n"
        "4. Speculate on the market outlook based on current market conditions.\n"
        "5. Identify potential market risks and suggest risk management strategies.\n\n"
        f"Here is my current portfolio data: {portfolio_data}\n"
        f"Here are my open orders: {open_orders}\n\n"
        f"Overall, answer the following question with priority having that background: {message}\n"
    )

    try:
        resp = anthropic_client.completions.create(
            model="claude-2.1",
            prompt=pre_prompt,
            max_tokens_to_sample=512,
        )
    except Exception as e:
        logging.exception("Anthropic completion failed")
        return f"Anthropic request failed: {e}"

    # The response object may be a dict-like or have an attribute; handle both.
    completion = None
    if isinstance(resp, dict):
        completion = resp.get("completion") or resp.get("text")
    else:
        completion = getattr(resp, "completion", None) or getattr(resp, "text", None)

    return completion or str(resp)

class TradingBotGUI:

    def __init__(self, root):
        self.root = root
        self.root.title("Trading Bot")
        self.cryptos = self.load_cryptos()
        self.system_running = False

        self.form_frame = tk.Frame(root)
        self.form_frame.pack(pady=10)

        # Add new crypto to trading bot
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

        # Table to track traded cryptos
        self.tree = ttk.Treeview(root, columns=("Symbol", "Position", "Entry Price", "Levels", "Status"), show='headings')
        for col in ["Symbol", "Position", "Entry Price", "Levels", "Status"]:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=120)
        self.tree.pack(pady=10)

        # Buttons to control the bot
        self.toggle_system_button = tk.Button(root, text="Toggle Selected System", command=self.toggle_selected_system)
        self.toggle_system_button.pack(pady=5)

        self.remove_button = tk.Button(root, text="Remove Selected crypto", command=self.remove_selected_crypto)
        self.remove_button.pack(pady=5)

        # AI Component
        self.chat_frame = tk.Frame(root)
        self.chat_frame.pack(pady=10)

        self.chat_input = tk.Entry(self.chat_frame, width=50)
        self.chat_input.grid(row=0, column=0, padx=5)

        self.send_button = tk.Button(self.chat_frame, text="Send", command=self.send_message)
        self.send_button.grid(row=0, column=1)

        self.chat_output = tk.Text(root, height=5, width=60, state=tk.DISABLED)
        self.chat_output.pack()

        # Firi test button
        self.test_button = tk.Button(root, text="Test Firi connection", command=self.test_firi_connection)
        self.test_button.pack(pady=5)

        # Load saved data
        self.refresh_table()

        # Auto_refershing
        self.running = True
        self.auto_update_thread = threading.Thread(target=self.auto_update, daemon=True)
        self.auto_update_thread.start()

        # Warn user if Firi API client is not configured
        if api is None:
            messagebox.showwarning(
                "Firi Not Configured",
                "Firi API client not configured. Export FIRI_API_KEY and FIRI_SECRET_KEY to enable trading."
            )


    def add_crypto(self):
        symbol = self.symbol_entry.get().upper()
        levels = self.levels_entry.get()
        drawdown = self.drawdown_entry.get()

        if not symbol or not levels.isdigit() or not drawdown.replace('.', '', 1).isdigit():
            messagebox.showerror("Error", "Invalid Input")
            return
        
        levels = int(levels)
        drawdown = float(drawdown) / 100
        entry_price = fetch_mock_api(symbol)["price"]

        level_prices = {i+1 : round(entry_price * (1-drawdown*(i+1)), 2) for i in range(levels)}

        self.cryptos[symbol] = {
            "position": 0,
            "entry_price": entry_price,
            "levels": level_prices,
            "drawdown": drawdown,
            "status": "Off"
        }
        self.save_cryptos()
        self.refresh_table()

    def toggle_selected_system(self):
        selected_items = self.tree.selection()
        if not selected_items:
            messagebox.showerror("Error", "No crypto selected")
            return
        
        for item in selected_items:
            symbol = self.tree.item(item)['values'][0]
            # Normalize to consistent casing 'On'/'Off'
            current = str(self.cryptos.get(symbol, {}).get('status', 'Off'))
            self.cryptos[symbol]['status'] = "On" if current == "Off" else "Off"

        self.save_cryptos()
        self.refresh_table()

    def remove_selected_crypto(self):
        selected_items = self.tree.selection()
        if not selected_items:
            messagebox.showwarning("Warning", "No crypto selected")
            return
        
        for item in selected_items:
            symbol = self.tree.item(item)['values'][0]
            if symbol in self.cryptos:
                del self.cryptos[symbol]

        self.save_cryptos()
        self.refresh_table()

    def send_message(self):
        message = self.chat_input.get()
        if not message:
            return
        
        response = chatgpt_response(message)
        
        self.chat_output.config(state=tk.NORMAL)
        self.chat_output.insert(tk.END, f"You: {message}\n{response}\n\n")
        self.chat_output.config(state=tk.DISABLED)
        self.chat_input.delete(0, tk.END)

    def fetch_firi_data(self, symbol):
        if api is None:
            return {"price": -1}
        try:
            barset = api.get_latest_trade(symbol)
            return {"price": getattr(barset, 'price', -1)}
        except Exception:
            return {"price": -1}

    def check_existing_orders(self, symbol, price): 
        if api is None:
            return False
        try:
            orders = api.list_orders(status='open', symbols=symbol)
            for order in orders:
                try:
                    if float(order.limit_price) == price:
                        return True
                except Exception:
                    continue
        except Exception as e:
            messagebox.showerror("API Error", f"Error checking orders: {e}")
        return False
    
    def get_max_entry_price(self, symbol):
        if api is None:
            return -1
        try:
            orders = api.list_orders(status='filled', limit=50)
            prices = []
            for order in orders:
                try:
                    if getattr(order, 'symbol', None) == symbol and getattr(order, 'filled_avg_price', None):
                        prices.append(float(order.filled_avg_price))
                except Exception:
                    continue
            return max(prices) if prices else -1
        except Exception as e:
            messagebox.showerror("API Error", f"Error fetching orders: {e}")
            return -1

    def trade_systems(self):
        if api is None:
            # Trading disabled when no API client is configured
            return
        for symbol, data in self.cryptos.items():
            if data['status'] == 'On':
                position_exists = False
                try:
                    position = api.get_position(symbol)
                    entry_price = self.get_max_entry_price(symbol)
                    position_exists = True
                except Exception as e:
                    api.submit_order(
                        symbol = symbol,
                        qty = 1,
                        side = "buy",
                        type = "market",
                        time_in_force = "gtc"
                    )
                    messagebox.showinfo("Order Placed", f"Initial Order Placed for {symbol}")
                    time.sleep(2)
                    entry_price = self.get_max_entry_price(symbol)
                print(entry_price)

                level_prices = {i+1 : round(entry_price * (1-data['drawdown']*(i+1)), 2) for i in range(len(data['levels']))}
                existing_levels = self.cryptos.get(symbol, {}).get("levels", {})
                for level, price in level_prices.items():
                    if level not in existing_levels and -level not in existing_levels:
                        existing_levels[level] = price

                self.cryptos[symbol]['entry_price'] = entry_price
                self.cryptos[symbol]['levels'] = existing_levels
                self.cryptos[symbol]['position'] = 1

                for level, price in level_prices.items():
                    if level in self.cryptos[symbol]['levels']:
                        self.place_order(symbol, price, level)

            self.save_cryptos()
            self.refresh_table()
        else:
            return 
        
    def place_order(self, symbol, price, level):
        if -level in self.cryptos[symbol]['levels'] or '-1' in self.cryptos[symbol]['levels'].keys():
            return
        
        try:
            if api is None:
                raise RuntimeError("Firi API client not configured")
            api.submit_order(
                symbol=symbol,
                qty=1,
                side="buy",
                type="limit",
                time_in_force="gtc",
                limit_price=price
            )
            self.cryptos[symbol]['levels'][-level] = price
            del self.cryptos[symbol]['levels'][level]
            print(f"Placed order for {symbol}@{price}")
        except Exception as e:
            messagebox.showerror("Order Error", f"Error placing order {e}")

    def test_firi_connection(self):
        if api is None:
            messagebox.showwarning("Firi Not Configured", "Firi API client is not configured. Export FIRI_API_KEY and FIRI_SECRET_KEY.")
            return

        checks = [
            ('list_positions', False),
            ('list_orders', True),
            ('get_account', False),
            ('get_balance', False),
        ]
        results = []
        for name, takes_args in checks:
            if hasattr(api, name):
                try:
                    fn = getattr(api, name)
                    if takes_args:
                        val = fn(status='open')
                    else:
                        val = fn()
                    try:
                        results.append(f"{name}: returned {len(val)} items")
                    except Exception:
                        results.append(f"{name}: returned {repr(val)}")
                except Exception as e:
                    results.append(f"{name}: error {e}")
            else:
                results.append(f"{name}: not available on client")

        messagebox.showinfo("Firi Test Results", "\n".join(results))


    def refresh_table(self):
        for row in self.tree.get_children():
            self.tree.delete(row)

        for symbol, data in self.cryptos.items():
            self.tree.insert("", "end", values=(
                symbol,
                data["position"],
                data["entry_price"],
                str(data["levels"]),
                data["status"]
            ))

    def auto_update(self):
        while self.running:
            time.sleep(5)
            self.trade_systems()

    def save_cryptos(self):
        with open(DATA_FILE, 'w') as f:
            json.dump(self.cryptos, f)
    
    def load_cryptos(self):
        try:
            with open(DATA_FILE, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}
    
    def on_close(self):
        self.running = False
        self.save_cryptos()
        self.root.destroy()
    
if __name__ == "__main__":
    root = tk.Tk()
    app = TradingBotGUI(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()