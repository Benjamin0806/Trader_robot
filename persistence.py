"""
Persistence: Save and restore bot state, grid configuration, and open orders.
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict


STATE_DIR = Path("state")
STATE_DIR.mkdir(exist_ok=True)

STATE_FILE = STATE_DIR / "bot_state.json"
CONFIG_FILE = STATE_DIR / "grid_config.json"
ORDERS_FILE = STATE_DIR / "open_orders.json"


@dataclass
class GridConfig:
    """Per-symbol grid configuration."""
    symbol: str
    num_levels: int = 5
    enabled: bool = False
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict) -> "GridConfig":
        return cls(**data)


class PersistenceManager:
    """Manages saving and restoring bot state."""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
    
    def save_bot_state(self, state: dict):
        """Save bot operational state."""
        try:
            with open(STATE_FILE, 'w') as f:
                json.dump(state, f, indent=2, default=str)
            self.logger.debug(f"Bot state saved to {STATE_FILE}")
        except Exception as e:
            self.logger.error(f"Failed to save bot state: {e}")
    
    def load_bot_state(self) -> dict:
        """Load bot operational state."""
        try:
            if STATE_FILE.exists():
                with open(STATE_FILE, 'r') as f:
                    return json.load(f)
        except Exception as e:
            self.logger.error(f"Failed to load bot state: {e}")
        return {}
    
    def save_grid_configs(self, configs: Dict[str, GridConfig]):
        """Save grid configurations for all symbols."""
        try:
            data = {symbol: cfg.to_dict() for symbol, cfg in configs.items()}
            with open(CONFIG_FILE, 'w') as f:
                json.dump(data, f, indent=2)
            self.logger.debug(f"Grid configs saved to {CONFIG_FILE}")
        except Exception as e:
            self.logger.error(f"Failed to save grid configs: {e}")
    
    def load_grid_configs(self) -> Dict[str, GridConfig]:
        """Load grid configurations."""
        try:
            if CONFIG_FILE.exists():
                with open(CONFIG_FILE, 'r') as f:
                    data = json.load(f)
                    return {symbol: GridConfig.from_dict(cfg) for symbol, cfg in data.items()}
        except Exception as e:
            self.logger.error(f"Failed to load grid configs: {e}")
        return {}
    
    def save_open_orders(self, orders: List[Dict[str, Any]]):
        """Save open orders for recovery."""
        try:
            with open(ORDERS_FILE, 'w') as f:
                json.dump(orders, f, indent=2, default=str)
            self.logger.debug(f"Open orders saved to {ORDERS_FILE}")
        except Exception as e:
            self.logger.error(f"Failed to save open orders: {e}")
    
    def load_open_orders(self) -> List[Dict[str, Any]]:
        """Load open orders from last session."""
        try:
            if ORDERS_FILE.exists():
                with open(ORDERS_FILE, 'r') as f:
                    return json.load(f)
        except Exception as e:
            self.logger.error(f"Failed to load open orders: {e}")
        return []
    
    def clear_state(self):
        """Clear all saved state (for reset)."""
        try:
            STATE_FILE.unlink(missing_ok=True)
            CONFIG_FILE.unlink(missing_ok=True)
            ORDERS_FILE.unlink(missing_ok=True)
            self.logger.info("Bot state cleared")
        except Exception as e:
            self.logger.error(f"Failed to clear state: {e}")


# Global instance
_persistence_manager = PersistenceManager()


def get_persistence_manager() -> PersistenceManager:
    """Get the global persistence manager."""
    return _persistence_manager
