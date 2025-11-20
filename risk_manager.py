"""
Risk Manager: Global kill-switch, capital allocation, pre-trade validations.
"""

import logging
from dataclasses import dataclass
from typing import Dict, Optional
from enum import Enum


class BotState(Enum):
    """Bot trading state."""
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass
class RiskConfig:
    """Risk management configuration."""
    # Kill switch: set to True to halt all trading
    trading_enabled: bool = True
    
    # Capital allocation (% of total portfolio per symbol)
    max_capital_per_symbol: float = 0.20  # 20%
    
    # Maximum total portfolio exposure
    max_total_exposure: float = 0.80  # 80%
    
    # Minimum spread protection (% of price)
    min_spread_pct: float = 0.05  # 0.05%
    
    # Circuit breaker: pause if ATR changes by this % in one candle
    atr_spike_circuit_breaker: float = 0.30  # 30%
    
    # Max slippage allowed (% of order price)
    max_slippage_pct: float = 0.02  # 2%
    
    # Dry-run mode (don't submit real orders)
    dry_run: bool = False
    
    # Minimum order amount (in base currency, e.g., NOK)
    min_order_value: float = 100.0


class RiskManager:
    """Manages trading risk controls, kill-switch, and pre-trade validations."""
    
    def __init__(self, config: Optional[RiskConfig] = None):
        self.config = config or RiskConfig()
        self.state = BotState.RUNNING
        self.logger = logging.getLogger(__name__)
        self.portfolio_value = 0.0  # Current portfolio value in NOK/USD
        self.current_exposure = 0.0  # Current total exposure %
        self.symbol_exposure: Dict[str, float] = {}  # Per-symbol exposure %
        
    def set_trading_enabled(self, enabled: bool):
        """Toggle global kill-switch."""
        self.config.trading_enabled = enabled
        state = "ENABLED" if enabled else "DISABLED"
        self.logger.warning(f"🚨 Global kill-switch: Trading {state}")
        
    def set_state(self, state: BotState):
        """Set bot operational state."""
        self.state = state
        self.logger.info(f"Bot state changed to: {state.value}")
    
    def update_portfolio_value(self, portfolio: list, current_prices: Dict[str, float]):
        """Update current portfolio value and exposure metrics."""
        total_value = 0.0
        self.symbol_exposure = {}
        
        for item in portfolio:
            symbol = item.get("symbol", "")
            qty = float(item.get("qty", 0))
            price = current_prices.get(symbol, item.get("current_price", 0))
            
            value = qty * price
            total_value += value
            
            if total_value > 0:
                self.symbol_exposure[symbol] = (value / total_value) * 100
        
        self.portfolio_value = total_value
        self.current_exposure = sum(self.symbol_exposure.values())
        
        self.logger.debug(f"Portfolio value: {total_value:.2f}, Exposure: {self.current_exposure:.1f}%")
    
    def can_trade_symbol(self, symbol: str, position_value: float) -> tuple[bool, str]:
        """
        Check if we can trade this symbol based on risk limits.
        Returns: (allowed: bool, reason: str)
        """
        if not self.config.trading_enabled:
            return False, "Trading disabled (kill-switch active)"
        
        if self.state != BotState.RUNNING:
            return False, f"Bot not running (state: {self.state.value})"
        
        # Check per-symbol capital allocation
        if self.portfolio_value > 0:
            new_exposure = (position_value / self.portfolio_value) * 100
            max_allowed = self.config.max_capital_per_symbol * 100
            
            if new_exposure > max_allowed:
                return False, f"Exceeds max capital/symbol ({new_exposure:.1f}% > {max_allowed:.1f}%)"
        
        # Check total exposure
        if self.current_exposure >= self.config.max_total_exposure * 100:
            return False, f"Max portfolio exposure reached ({self.current_exposure:.1f}%)"
        
        return True, "OK"
    
    def validate_order(self, symbol: str, qty: float, price: float, side: str) -> tuple[bool, str]:
        """
        Pre-trade validations.
        Returns: (valid: bool, reason: str)
        """
        if qty <= 0:
            return False, "Quantity must be positive"
        
        if price <= 0:
            return False, "Price must be positive"
        
        # Check minimum order value
        order_value = qty * price
        if order_value < self.config.min_order_value:
            return False, f"Order value ({order_value:.2f}) below minimum ({self.config.min_order_value:.2f})"
        
        return True, "OK"
    
    def check_circuit_breaker(self, current_atr: float, previous_atr: float) -> tuple[bool, str]:
        """
        Detect extreme ATR changes (volatility spike circuit breaker).
        Returns: (passed: bool, reason: str)
        """
        if previous_atr is None or previous_atr <= 0:
            return True, "No previous ATR"
        
        atr_change = abs(current_atr - previous_atr) / previous_atr
        threshold = self.config.atr_spike_circuit_breaker
        
        if atr_change > threshold:
            return False, f"ATR spike detected ({atr_change*100:.1f}% > {threshold*100:.1f}%)"
        
        return True, "OK"
    
    def check_spread(self, bid: float, ask: float) -> tuple[bool, str]:
        """
        Check if bid-ask spread is within acceptable range.
        Returns: (acceptable: bool, reason: str)
        """
        if bid <= 0 or ask <= 0:
            return False, "Invalid bid/ask"
        
        spread_pct = (ask - bid) / bid * 100
        max_spread = self.config.min_spread_pct
        
        if spread_pct > max_spread:
            return False, f"Spread too wide ({spread_pct:.4f}% > {max_spread:.4f}%)"
        
        return True, "OK"
    
    def get_status(self) -> dict:
        """Return current risk status."""
        return {
            "trading_enabled": self.config.trading_enabled,
            "bot_state": self.state.value,
            "portfolio_value": self.portfolio_value,
            "total_exposure": self.current_exposure,
            "symbol_exposure": self.symbol_exposure,
            "dry_run": self.config.dry_run,
        }
