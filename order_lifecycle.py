"""
Order Lifecycle Manager: Poll order status, detect fills, manage take-profit, auto-cancel.
"""

import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
from datetime import datetime, timedelta


class OrderStatus(Enum):
    """Order status enum."""
    OPEN = "open"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


@dataclass
class Order:
    """Order representation."""
    order_id: str
    symbol: str
    side: str  # "buy" or "sell"
    qty: float
    filled_qty: float = 0.0
    price: float = 0.0
    status: OrderStatus = OrderStatus.OPEN
    created_at: datetime = None
    updated_at: datetime = None
    grid_level: int = 0
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()
        if self.updated_at is None:
            self.updated_at = datetime.now()
    
    def is_expired(self, timeout_hours: int = 24) -> bool:
        """Check if order is expired."""
        return datetime.now() - self.created_at > timedelta(hours=timeout_hours)
    
    def to_dict(self) -> dict:
        """Convert to dict for serialization."""
        return {
            "order_id": self.order_id,
            "symbol": self.symbol,
            "side": self.side,
            "qty": self.qty,
            "filled_qty": self.filled_qty,
            "price": self.price,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "grid_level": self.grid_level,
        }


class OrderLifecycleManager:
    """Manages order lifecycle: polling, fills, TP, cancellation."""
    
    def __init__(self, firi_client=None):
        self.firi = firi_client
        self.logger = logging.getLogger(__name__)
        self.orders: Dict[str, Order] = {}  # order_id -> Order
        self.pending_tp_orders: Dict[str, str] = {}  # buy_order_id -> sell_order_id (TP)
        self.filled_levels: Dict[str, set] = {}  # symbol -> set of filled grid levels
    
    def register_order(self, order: Order):
        """Register a new order in the tracker."""
        self.orders[order.order_id] = order
        self.logger.info(f"Order registered: {order.order_id} ({order.symbol} {order.side})")
    
    def poll_order_status(self, order_id: str) -> Optional[Order]:
        """Poll Firi for order status and update local record."""
        if order_id not in self.orders:
            return None
        
        if not self.firi:
            return self.orders[order_id]
        
        try:
            # Query Firi for this specific order
            # (Firi API may not support single order query, so we fetch all orders)
            # TODO: Implement based on actual Firi API
            pass
        except Exception as e:
            self.logger.error(f"Failed to poll order {order_id}: {e}")
        
        return self.orders.get(order_id)
    
    def poll_all_orders(self) -> List[Order]:
        """Poll all open orders and update statuses."""
        if not self.firi:
            return []
        
        try:
            open_orders = self.firi.list_orders(status="open")
            
            # Update local order statuses based on Firi response
            # (Exact parsing depends on Firi API format)
            for firi_order in open_orders:
                order_id = firi_order.get("id")
                if order_id in self.orders:
                    self.orders[order_id].filled_qty = float(firi_order.get("amount_filled", 0))
                    self.orders[order_id].updated_at = datetime.now()
            
            # Check for filled orders
            filled_orders = [o for o in self.orders.values() if o.status == OrderStatus.FILLED]
            return filled_orders
        
        except Exception as e:
            self.logger.error(f"Failed to poll orders: {e}")
            return []
    
    def mark_filled(self, order_id: str, filled_qty: float = None):
        """Mark order as filled."""
        if order_id not in self.orders:
            return
        
        order = self.orders[order_id]
        if filled_qty is None:
            filled_qty = order.qty
        
        order.filled_qty = filled_qty
        order.status = OrderStatus.FILLED if filled_qty >= order.qty else OrderStatus.PARTIALLY_FILLED
        order.updated_at = datetime.now()
        
        self.logger.info(f"Order marked filled: {order_id} ({filled_qty}/{order.qty})")
        
        # Track filled grid level for this symbol
        if order.symbol not in self.filled_levels:
            self.filled_levels[order.symbol] = set()
        self.filled_levels[order.symbol].add(order.grid_level)
    
    def mark_cancelled(self, order_id: str, reason: str = ""):
        """Mark order as cancelled."""
        if order_id not in self.orders:
            return
        
        order = self.orders[order_id]
        order.status = OrderStatus.CANCELLED
        order.updated_at = datetime.now()
        
        self.logger.info(f"Order marked cancelled: {order_id} ({reason})")
    
    def get_filled_levels(self, symbol: str) -> set:
        """Get grid levels that have been filled for a symbol."""
        return self.filled_levels.get(symbol, set())
    
    def remove_order(self, order_id: str):
        """Remove order from tracking."""
        if order_id in self.orders:
            del self.orders[order_id]
            self.logger.debug(f"Order removed from tracking: {order_id}")
    
    def get_open_orders(self) -> List[Order]:
        """Get all open/partially-filled orders."""
        return [o for o in self.orders.values() if o.status in (OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED)]
    
    def get_order(self, order_id: str) -> Optional[Order]:
        """Get order by ID."""
        return self.orders.get(order_id)
    
    def cancel_outdated_orders(self, timeout_hours: int = 24) -> List[str]:
        """Cancel orders older than timeout."""
        outdated = [o.order_id for o in self.orders.values() 
                    if o.is_expired(timeout_hours) and o.status == OrderStatus.OPEN]
        
        for order_id in outdated:
            self.mark_cancelled(order_id, reason="Expired")
        
        return outdated
    
    def get_status(self) -> dict:
        """Get overall order lifecycle status."""
        open_orders = self.get_open_orders()
        filled_orders = [o for o in self.orders.values() if o.status == OrderStatus.FILLED]
        cancelled_orders = [o for o in self.orders.values() if o.status == OrderStatus.CANCELLED]
        
        return {
            "total_orders": len(self.orders),
            "open_orders": len(open_orders),
            "filled_orders": len(filled_orders),
            "cancelled_orders": len(cancelled_orders),
            "open_orders_list": [o.to_dict() for o in open_orders],
        }
