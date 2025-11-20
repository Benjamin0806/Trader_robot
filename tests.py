"""
Unit tests for core trading bot components.
Run with: python -m pytest tests.py -v
"""

import unittest
from datetime import datetime
from risk_manager import RiskManager, RiskConfig, BotState
from order_lifecycle import Order, OrderStatus, OrderLifecycleManager
from persistence import GridConfig, PersistenceManager


class TestRiskManager(unittest.TestCase):
    """Test risk management and safety controls."""
    
    def setUp(self):
        self.config = RiskConfig(
            max_capital_per_symbol=0.20,
            max_total_exposure=0.80,
            dry_run=True
        )
        self.risk_mgr = RiskManager(self.config)
    
    def test_kill_switch(self):
        """Test global kill-switch."""
        self.risk_mgr.set_trading_enabled(False)
        can_trade, reason = self.risk_mgr.can_trade_symbol("BTCNOK", 1000)
        self.assertFalse(can_trade)
        self.assertIn("kill-switch", reason.lower())
    
    def test_capital_allocation(self):
        """Test per-symbol capital allocation limit."""
        self.risk_mgr.portfolio_value = 10000
        
        # Update portfolio
        portfolio = [
            {"symbol": "BTCNOK", "qty": 0.2, "current_price": 50000}
        ]
        current_prices = {"BTCNOK": 50000}
        self.risk_mgr.update_portfolio_value(portfolio, current_prices)
        
        # Try to allocate more than 20%
        position_value = 2500  # 25% of 10000
        can_trade, reason = self.risk_mgr.can_trade_symbol("BTCNOK", position_value)
        self.assertFalse(can_trade)
    
    def test_order_validation(self):
        """Test pre-trade order validation."""
        # Invalid: zero quantity
        valid, reason = self.risk_mgr.validate_order("BTCNOK", 0, 50000, "buy")
        self.assertFalse(valid)
        
        # Invalid: negative price
        valid, reason = self.risk_mgr.validate_order("BTCNOK", 1, -50000, "buy")
        self.assertFalse(valid)
        
        # Valid order
        valid, reason = self.risk_mgr.validate_order("BTCNOK", 1, 50000, "buy")
        self.assertTrue(valid)
    
    def test_circuit_breaker(self):
        """Test ATR spike circuit breaker."""
        previous_atr = 100
        
        # Normal ATR change (20%)
        current_atr = 120
        passed, reason = self.risk_mgr.check_circuit_breaker(current_atr, previous_atr)
        self.assertTrue(passed)
        
        # Extreme ATR spike (50% > 30% threshold)
        current_atr = 150
        passed, reason = self.risk_mgr.check_circuit_breaker(current_atr, previous_atr)
        self.assertFalse(passed)
        self.assertIn("spike", reason.lower())
    
    def test_spread_check(self):
        """Test bid-ask spread validation."""
        bid = 50000
        ask = 50001
        
        # Tight spread (0.002%)
        passed, reason = self.risk_mgr.check_spread(bid, ask)
        self.assertTrue(passed)
        
        # Wide spread (0.1% > 0.05% threshold)
        ask = 50050
        passed, reason = self.risk_mgr.check_spread(bid, ask)
        self.assertFalse(passed)


class TestOrderLifecycle(unittest.TestCase):
    """Test order lifecycle management."""
    
    def setUp(self):
        self.order_mgr = OrderLifecycleManager()
    
    def test_order_registration(self):
        """Test order registration."""
        order = Order(
            order_id="123",
            symbol="BTCNOK",
            side="buy",
            qty=1.0,
            price=50000
        )
        self.order_mgr.register_order(order)
        
        retrieved = self.order_mgr.get_order("123")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.symbol, "BTCNOK")
    
    def test_order_fill_detection(self):
        """Test order fill marking."""
        order = Order(
            order_id="124",
            symbol="BTCNOK",
            side="buy",
            qty=1.0,
            price=50000
        )
        self.order_mgr.register_order(order)
        
        # Mark as filled
        self.order_mgr.mark_filled("124", filled_qty=1.0)
        
        updated = self.order_mgr.get_order("124")
        self.assertEqual(updated.status, OrderStatus.FILLED)
        self.assertEqual(updated.filled_qty, 1.0)
    
    def test_partial_fill(self):
        """Test partial fill detection."""
        order = Order(
            order_id="125",
            symbol="BTCNOK",
            side="buy",
            qty=2.0,
            price=50000
        )
        self.order_mgr.register_order(order)
        
        # Partial fill
        self.order_mgr.mark_filled("125", filled_qty=0.5)
        
        updated = self.order_mgr.get_order("125")
        self.assertEqual(updated.status, OrderStatus.PARTIALLY_FILLED)
        self.assertEqual(updated.filled_qty, 0.5)
    
    def test_grid_level_tracking(self):
        """Test filled grid level tracking."""
        # Fill orders at different levels
        for level in [1, 2, 3]:
            order = Order(
                order_id=f"order_{level}",
                symbol="BTCNOK",
                side="buy",
                qty=1.0,
                price=50000 - (level * 1000),
                grid_level=level
            )
            self.order_mgr.register_order(order)
            self.order_mgr.mark_filled(f"order_{level}")
        
        filled_levels = self.order_mgr.get_filled_levels("BTCNOK")
        self.assertEqual(filled_levels, {1, 2, 3})


class TestGridConfig(unittest.TestCase):
    """Test grid configuration persistence."""
    
    def test_grid_config_serialization(self):
        """Test GridConfig to/from dict conversion."""
        config = GridConfig(symbol="BTCNOK", num_levels=5, enabled=True)
        
        # Convert to dict
        data = config.to_dict()
        self.assertEqual(data["symbol"], "BTCNOK")
        self.assertEqual(data["num_levels"], 5)
        
        # Reconstruct from dict
        restored = GridConfig.from_dict(data)
        self.assertEqual(restored.symbol, "BTCNOK")
        self.assertEqual(restored.num_levels, 5)
        self.assertTrue(restored.enabled)


class TestOrderToDict(unittest.TestCase):
    """Test Order serialization."""
    
    def test_order_to_dict(self):
        """Test Order to dict conversion."""
        order = Order(
            order_id="126",
            symbol="BTCNOK",
            side="sell",
            qty=1.0,
            price=51000,
            status=OrderStatus.FILLED,
            grid_level=2
        )
        
        data = order.to_dict()
        self.assertEqual(data["order_id"], "126")
        self.assertEqual(data["symbol"], "BTCNOK")
        self.assertEqual(data["side"], "sell")
        self.assertEqual(data["status"], "filled")
        self.assertEqual(data["grid_level"], 2)


class TestBotState(unittest.TestCase):
    """Test bot state management."""
    
    def test_state_transitions(self):
        """Test bot state transitions."""
        risk_mgr = RiskManager()
        
        self.assertEqual(risk_mgr.state, BotState.RUNNING)
        
        risk_mgr.set_state(BotState.PAUSED)
        self.assertEqual(risk_mgr.state, BotState.PAUSED)
        
        risk_mgr.set_state(BotState.STOPPED)
        self.assertEqual(risk_mgr.state, BotState.STOPPED)


if __name__ == "__main__":
    unittest.main()
