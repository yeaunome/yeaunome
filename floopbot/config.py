"""
Trading configuration for Floopbot replay testing.

Mirrors the settings from FLOOP Pro indicator and Floopbot dashboard:
- ATR stop multiplier
- Trail distance
- Min signal strength
- Position sizing
"""

import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path

CONFIG_FILE = Path(__file__).parent / "floop_config.json"

@dataclass
class TradingConfig:
    # Signal filters
    min_signal_strength: int = 8
    max_signal_strength: int = 14

    # Risk management
    atr_stop_multiplier: float = 1.5
    trail_distance_atr: float = 1.0
    trail_mode: str = "adaptive"  # "adaptive" or "fixed"

    # Position sizing
    contracts: int = 1
    max_daily_loss: float = 1200.0  # dollars
    max_daily_trades: int = 20

    # Symbol defaults
    symbol: str = "MNQ1!"
    timeframe: str = "5"  # minutes
    tick_size: float = 0.25
    tick_value: float = 0.50  # dollars per tick for MNQ

    # Replay settings
    replay_start_date: str = ""  # YYYY-MM-DD, empty = first available
    replay_speed_ms: int = 0  # autoplay delay, 0 = fastest
    step_mode: bool = False  # True = step one bar at a time, False = autoplay
    bars_to_run: int = 0  # 0 = unlimited

    # MCP connection
    mcp_cli_path: str = ""  # auto-detected if empty
    cdp_host: str = "localhost"
    cdp_port: int = 9222

    # FLOOP Pro indicator name (as it appears on chart)
    floop_indicator_name: str = "FLOOP Pro"

    # Logging
    log_trades: bool = True
    log_signals: bool = True
    screenshot_on_trade: bool = True
    output_dir: str = "replay_results"

    def __post_init__(self):
        if not self.mcp_cli_path:
            # Auto-detect: check common locations
            candidates = [
                os.path.expanduser("~/tradingview-mcp/src/cli/index.js"),
                os.path.expanduser("~/tradingview-mcp/src/server.js"),
                str(Path(__file__).parent.parent.parent / "tradingview-mcp" / "src" / "cli" / "index.js"),
            ]
            for c in candidates:
                if os.path.isfile(c):
                    self.mcp_cli_path = c
                    break

    def save(self, path=None):
        p = Path(path) if path else CONFIG_FILE
        p.write_text(json.dumps(asdict(self), indent=2))

    @classmethod
    def load(cls, path=None):
        p = Path(path) if path else CONFIG_FILE
        if p.exists():
            data = json.loads(p.read_text())
            return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        return cls()

    @property
    def point_value(self):
        """Dollar value per 1.0 price point move."""
        return self.tick_value / self.tick_size

    def dollar_value(self, price_change):
        """Convert a price change to dollar P&L for configured contracts."""
        return price_change * self.point_value * self.contracts
