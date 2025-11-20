"""
Structured logging with JSON output and file export.
"""

import logging
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict


LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)


class StructuredLogger:
    """Logs trading events in structured JSON format."""
    
    def __init__(self, name: str = "trading_bot"):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.DEBUG)
        
        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_fmt = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        )
        console_handler.setFormatter(console_fmt)
        self.logger.addHandler(console_handler)
        
        # File handler (JSON)
        now = datetime.now().strftime("%Y%m%d_%H%M%S")
        json_file = LOG_DIR / f"trading_{now}.jsonl"
        self.json_file = json_file
        file_handler = logging.FileHandler(json_file)
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter("%(message)s"))
        self.logger.addHandler(file_handler)
        
        self.logger.info(f"🔧 Logging initialized. JSON log: {json_file}")
    
    def _log_json(self, level: str, message: str, **kwargs):
        """Log as JSON line."""
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "level": level,
            "message": message,
            **kwargs
        }
        # Convert to JSON and log via standard logger
        json_str = json.dumps(log_entry, default=str)
        if level == "ERROR":
            self.logger.error(json_str)
        elif level == "WARNING":
            self.logger.warning(json_str)
        elif level == "INFO":
            self.logger.info(json_str)
        else:
            self.logger.debug(json_str)
    
    # Trading events
    
    def log_order_placed(self, symbol: str, side: str, qty: float, price: float, 
                         order_id: str = "", grid_level: int = 0):
        """Log order placement."""
        self._log_json(
            "INFO",
            f"ORDER_PLACED: {symbol} {side.upper()} {qty} @ {price}",
            event="order_placed",
            symbol=symbol,
            side=side,
            qty=qty,
            price=price,
            order_id=order_id,
            grid_level=grid_level
        )
    
    def log_order_filled(self, symbol: str, side: str, qty: float, price: float, 
                        order_id: str = "", fill_qty: float = 0.0):
        """Log order fill."""
        self._log_json(
            "INFO",
            f"ORDER_FILLED: {symbol} {side.upper()} {fill_qty or qty} @ {price}",
            event="order_filled",
            symbol=symbol,
            side=side,
            qty=qty,
            fill_qty=fill_qty or qty,
            price=price,
            order_id=order_id
        )
    
    def log_order_cancelled(self, symbol: str, order_id: str, reason: str = ""):
        """Log order cancellation."""
        self._log_json(
            "INFO",
            f"ORDER_CANCELLED: {symbol} {order_id} ({reason})",
            event="order_cancelled",
            symbol=symbol,
            order_id=order_id,
            reason=reason
        )
    
    def log_grid_generated(self, symbol: str, trend: str, atr: float, 
                          buy_levels: Dict[int, float], sell_levels: Dict[int, float]):
        """Log grid generation."""
        self._log_json(
            "INFO",
            f"GRID_GENERATED: {symbol} trend={trend} atr={atr:.2f}",
            event="grid_generated",
            symbol=symbol,
            trend=trend,
            atr=atr,
            buy_levels=buy_levels,
            sell_levels=sell_levels
        )
    
    def log_risk_check(self, symbol: str, check_type: str, passed: bool, reason: str = ""):
        """Log risk validation."""
        level = "INFO" if passed else "WARNING"
        self._log_json(
            level,
            f"RISK_CHECK: {symbol} {check_type} {'PASSED' if passed else 'FAILED'} ({reason})",
            event="risk_check",
            symbol=symbol,
            check_type=check_type,
            passed=passed,
            reason=reason
        )
    
    def log_error(self, message: str, **kwargs):
        """Log error with context."""
        self._log_json("ERROR", message, event="error", **kwargs)
    
    def export_logs(self, output_file: str = "") -> str:
        """Export current logs to a file."""
        if not output_file:
            output_file = str(LOG_DIR / f"export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
        
        try:
            with open(self.json_file, 'r') as src:
                entries = [json.loads(line) for line in src if line.strip()]
            
            with open(output_file, 'w') as dst:
                json.dump(entries, dst, indent=2, default=str)
            
            self.logger.info(f"Logs exported to {output_file}")
            return output_file
        except Exception as e:
            self.logger.error(f"Failed to export logs: {e}")
            return ""
    
    def get_logger(self):
        """Return underlying logger for standard logging."""
        return self.logger


# Global instance
_structured_logger = StructuredLogger()


def get_logger() -> StructuredLogger:
    """Get the global structured logger."""
    return _structured_logger
