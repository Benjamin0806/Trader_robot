import tkinter as tk
from tkinter import ttk, messagebox
import json
import time
import threading
import random
import os
import logging
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
    if hasattr(firipy, "REST"):
        try:
            return firipy.REST(api_key, secret, base_url, api_version="v2")
        except Exception:
            pass
    if hasattr(firipy, "FiriAPI"):
        try:
            return firipy.FiriAPI(api_key, secret, base_url=base_url)
        except TypeError:
            return firipy.FiriAPI(api_key, secret)
    # As a last resort attempt to use firipy as a module with a client function
    try:
        return firipy.Client(api_key, secret, base_url)
    except Exception:
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

        # Load saved data
        self.refresh_table()

        # Auto_refershing
        self.running = True
        self.auto_update_thread = threading.Thread(target=self.auto_update, daemon=True)
        self.auto_update_thread.start()


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
            "status": "off"
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
            self.cryptos[symbol]['status'] = "On" if self.cryptos[symbol]['status'] == "Off" else "Off"

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
        try:
            barset = api.get_latest_trade(symbol)
            return {"price":barset.price}
        except Exception as e:
            return {"price":-1}

    def check_existing_orders(self, symbol, price): 
        try:
            orders = api.list_orders(status='open', symbols=symbol)
            for order in orders:
                if float(order.limit_price) == price:
                    return True
        except Exception as e:
            messagebox.showerror("API Error", "Error checking orders {e}")
        return False
    
    def get_max_entry_price(self, symbol):
        try:
            orders = api.list_orders(status='filled', limit=50)
            prices = [float(order.filled_avg_price) for order in orders if order.filled_avg_price and order.symbol == symbol]
            return max(prices) if prices else -1
        except Exception as e:
            messagebox.showerror("API Error", f"Error fetching orders {e}")
            return 0

    def trade_systems(self):
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
            print("Placed order for {symbol}@{price}")
        except Exception as e:
            messagebox.showerror("Order Error", f"Error placing order {e}")


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