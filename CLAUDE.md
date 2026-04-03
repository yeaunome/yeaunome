# Floopbot - Automated Replay Paper Trading

## Overview
Floopbot is a Python-based automated trading bot that connects to TradingView Desktop via the [tradingview-mcp](https://github.com/tradesdontlie/tradingview-mcp) bridge. It reads signals from the **FLOOP Pro** Pine Script indicator during TradingView's replay mode and paper trades them with full position management.

## Architecture

```
floopbot/
├── __init__.py         # Package init
├── __main__.py         # CLI entry point (python -m floopbot)
├── config.py           # TradingConfig dataclass with all settings
├── mcp_bridge.py       # TVBridge - wraps TradingView MCP CLI commands
├── signal_parser.py    # Parses FLOOP Pro labels/tables/values into signals
├── paper_trader.py     # PaperTrader engine - positions, stops, trails, P&L
├── replay_runner.py    # ReplayRunner orchestrator - main loop
├── report.py           # ReportGenerator - JSON/CSV/text reports
└── tests/
    └── test_paper_trader.py
```

## Key Components

- **TVBridge** (`mcp_bridge.py`): Calls `node tradingview-mcp/src/cli/index.js` commands. Methods mirror MCP tools: `replay_start()`, `get_pine_labels()`, `get_quote()`, etc.
- **SignalAggregator** (`signal_parser.py`): Deduplicates signals by tracking last-seen label count/text. Detects FLOOP LONG/SHORT/EXIT from Pine labels.
- **PaperTrader** (`paper_trader.py`): ATR-based stops, adaptive trailing, daily loss limits, MFE/MAE tracking, signal strength filtering.
- **ReplayRunner** (`replay_runner.py`): Step mode (one bar at a time) or autoplay mode. Reads signals, feeds to trader, generates reports.

## Running

```bash
# Prerequisites: TradingView Desktop with --remote-debugging-port=9222
# FLOOP Pro indicator must be on the chart

python -m floopbot --check                    # Test connection
python -m floopbot --save-config              # Create config file
python -m floopbot --symbol MNQ1! --tf 5      # Run replay test
python -m floopbot --bars 500 --step          # Step mode, 500 bars
python -m floopbot --date 2026-01-15          # Start from specific date
```

## Testing
```bash
python -m pytest floopbot/tests/ -v
python -m unittest floopbot.tests.test_paper_trader -v
```

## MCP Config
The project `.mcp.json` configures the TradingView MCP server. The global config at `~/.claude/.mcp.json` also works. The MCP server must point to the cloned tradingview-mcp repo's `src/server.js`.

## Signal Flow
1. TradingView replay advances bars
2. FLOOP Pro indicator evaluates and draws labels (FLOOP LONG/SHORT/EXIT)
3. `TVBridge.get_pine_labels()` reads labels via CDP
4. `SignalAggregator` detects new signals
5. `PaperTrader.on_signal()` opens/closes positions
6. `PaperTrader.on_bar()` manages stops and trailing on each bar
7. `ReportGenerator` writes results to JSON/CSV/text

## Config Reference
See `TradingConfig` in `config.py`. Key settings:
- `atr_stop_multiplier`: Initial stop distance in ATR units (default: 1.5)
- `trail_distance_atr`: Trail distance in ATR units (default: 1.0)
- `trail_mode`: "adaptive" (tightens with profit) or "fixed"
- `min_signal_strength`: Minimum FLOOP signal strength to trade (default: 8/14)
- `max_daily_loss`: Daily loss limit in dollars (default: $1200)
- `step_mode`: true = precise one-bar-at-a-time, false = autoplay (faster)
