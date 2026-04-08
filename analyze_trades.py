"""
Trade Analysis Script — Uses tradingview-mcp CLI to navigate to each trade entry,
capture screenshots, and measure MAE (Maximum Adverse Excursion).

Run on Windows where TradingView Desktop is running with CDP on port 9222:
    python analyze_trades.py

Screenshots saved to ./trade_screenshots/
"""

import subprocess
import json
import time
import os
import sys
from pathlib import Path
from datetime import datetime

# ── Config ──
MCP_CLI = str(Path(__file__).parent / "tradingview-mcp" / "src" / "cli" / "index.js")
SYMBOL = "MNQ1!"
TIMEFRAME = "1"  # 1 minute
SCREENSHOT_DIR = Path(__file__).parent / "trade_screenshots"

# Trades to analyze — Apr 6-7, 2026 CT
TRADES = [
    {"time": "2026-04-06 23:45", "side": "Short", "entry": 24336, "label": "11:45 PM"},
    {"time": "2026-04-07 00:03", "side": "Long",  "entry": 24264, "label": "12:03 AM"},
    {"time": "2026-04-07 00:00", "side": "Long",  "entry": 24287, "label": "12:00 AM"},
    {"time": "2026-04-07 00:20", "side": "Short", "entry": 24346, "label": "12:20 AM"},
    {"time": "2026-04-07 01:24", "side": "Long",  "entry": 24211, "label": "1:24 AM"},
    {"time": "2026-04-07 01:30", "side": "Short", "entry": 24240, "label": "1:30 AM"},
    {"time": "2026-04-07 05:30", "side": "Long",  "entry": 24225, "label": "5:30 AM (33 min hold)"},
    {"time": "2026-04-07 08:21", "side": "Short", "entry": 24354, "label": "8:21 AM (18 sec)"},
    {"time": "2026-04-07 09:48", "side": "Long",  "entry": 24166, "label": "9:48 AM"},
    {"time": "2026-04-07 12:36", "side": "Short", "entry": 24260, "label": "12:36 PM"},
]


def run_cli(*args, timeout=30):
    """Run tradingview-mcp CLI command and return parsed result."""
    cmd = ["node", MCP_CLI] + list(args)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                                encoding='utf-8', errors='replace')
        stdout = (result.stdout or "").strip()
        if result.returncode != 0:
            print(f"  CLI error: {result.stderr or result.returncode}")
            return None
        if not stdout:
            return {}
        try:
            return json.loads(stdout)
        except json.JSONDecodeError:
            return {"raw": stdout}
    except subprocess.TimeoutExpired:
        print(f"  CLI timeout after {timeout}s")
        return None
    except FileNotFoundError:
        print(f"  ERROR: node not found or CLI path invalid: {MCP_CLI}")
        sys.exit(1)


def setup_chart():
    """Set symbol and timeframe."""
    print(f"Setting symbol to {SYMBOL}...")
    run_cli("chart", "set-symbol", SYMBOL)
    time.sleep(2)

    print(f"Setting timeframe to {TIMEFRAME}m...")
    run_cli("chart", "set-timeframe", TIMEFRAME)
    time.sleep(2)


def get_ohlcv_bars(count=100):
    """Get recent OHLCV bars from the chart."""
    result = run_cli("data", "get-ohlcv", "--bars", str(count))
    if result and "bars" in result:
        return result["bars"]
    if result and "data" in result and "bars" in result["data"]:
        return result["data"]["bars"]
    return result


def scroll_to_date(date_str):
    """Scroll chart to a specific date. Format: YYYY-MM-DD or YYYY-MM-DD HH:MM"""
    result = run_cli("chart", "scroll-to-date", date_str)
    return result


def set_visible_range(start_date, end_date):
    """Set the visible range of the chart."""
    result = run_cli("chart", "set-visible-range", start_date, end_date)
    return result


def capture_screenshot(filename, region="chart"):
    """Capture screenshot and save to file."""
    result = run_cli("capture", "screenshot", "--region", region)
    if result and isinstance(result, dict):
        # The CLI might return base64 image data or save to file
        if "image" in result:
            import base64
            img_data = base64.b64decode(result["image"])
            with open(filename, "wb") as f:
                f.write(img_data)
            return True
        if "data" in result and "image" in result.get("data", {}):
            import base64
            img_data = base64.b64decode(result["data"]["image"])
            with open(filename, "wb") as f:
                f.write(img_data)
            return True
        if "path" in result:
            print(f"  Screenshot saved by CLI to: {result['path']}")
            return True
    # Try alternate: just save whatever came back
    print(f"  Screenshot result: {str(result)[:200]}")
    return False


def analyze_trade(trade, index):
    """Navigate to trade entry time and capture screenshot."""
    label = trade["label"]
    entry_time = trade["time"]
    side = trade["side"]
    entry_price = trade["entry"]

    print(f"\n{'='*60}")
    print(f"Trade #{index+1}: {label} — {side} @ {entry_price}")
    print(f"{'='*60}")

    # Scroll to the trade time
    print(f"  Scrolling to {entry_time}...")
    scroll_to_date(entry_time)
    time.sleep(3)

    # Capture screenshot
    filename = SCREENSHOT_DIR / f"trade_{index+1:02d}_{label.replace(' ', '_').replace(':', '')}.png"
    print(f"  Capturing screenshot...")
    capture_screenshot(str(filename))

    # Try to get OHLCV data around the entry for MAE analysis
    print(f"  Fetching bar data for MAE analysis...")
    bars = get_ohlcv_bars(60)  # Get 60 bars (1 hour of 1m data)

    if bars and isinstance(bars, list):
        # Calculate MAE — worst price move against the trade
        if side == "Long":
            # For longs, MAE = entry - lowest low after entry
            lows = [b.get("low", b.get("l", 0)) for b in bars if b.get("low", b.get("l", 0)) > 0]
            if lows:
                worst = min(lows)
                mae = entry_price - worst
                print(f"  Lowest low in window: {worst}")
                print(f"  MAE (adverse excursion): {mae:.2f} pts (${mae * 2:.2f} per contract)")
        else:
            # For shorts, MAE = highest high after entry - entry
            highs = [b.get("high", b.get("h", 0)) for b in bars if b.get("high", b.get("h", 0)) > 0]
            if highs:
                worst = max(highs)
                mae = worst - entry_price
                print(f"  Highest high in window: {worst}")
                print(f"  MAE (adverse excursion): {mae:.2f} pts (${mae * 2:.2f} per contract)")

    return bars


def capture_full_session():
    """Capture the full session overview (11:45 PM Apr 6 to 2:20 PM Apr 7)."""
    print(f"\n{'='*60}")
    print("Full Session Overview")
    print(f"{'='*60}")

    # Set visible range to cover the full session
    print("  Setting visible range for full session...")
    set_visible_range("2026-04-06 23:30", "2026-04-07 14:30")
    time.sleep(3)

    filename = SCREENSHOT_DIR / "00_full_session.png"
    print("  Capturing full session screenshot...")
    capture_screenshot(str(filename), region="full")


def main():
    # Create screenshot directory
    SCREENSHOT_DIR.mkdir(exist_ok=True)

    # Check CLI exists
    if not Path(MCP_CLI).exists():
        print(f"ERROR: tradingview-mcp CLI not found at: {MCP_CLI}")
        print(f"Make sure tradingview-mcp is cloned in the project directory.")
        sys.exit(1)

    # Check TradingView connection
    print("Checking TradingView connection...")
    health = run_cli("tv", "health-check")
    if not health:
        print("ERROR: Cannot connect to TradingView Desktop.")
        print("Make sure TradingView is running with --remote-debugging-port=9222")
        print("Run start_floopbot.bat first.")
        sys.exit(1)
    print(f"  Connected: {health}")

    # Setup chart
    setup_chart()

    # Capture full session overview
    capture_full_session()

    # Analyze each trade
    for i, trade in enumerate(TRADES):
        analyze_trade(trade, i)
        time.sleep(2)  # Brief pause between trades

    print(f"\n{'='*60}")
    print(f"Done! Screenshots saved to: {SCREENSHOT_DIR}")
    print(f"{'='*60}")
    print(f"\nKey trades to examine:")
    print(f"  - Trade #7 (5:30 AM Long, 33 min hold): How far did price dip before TP?")
    print(f"  - Trade #8 (8:21 AM Short, 18 sec): Clean entry or luck?")


if __name__ == "__main__":
    main()
