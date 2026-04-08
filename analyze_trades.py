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
import sys
import base64
import calendar
from pathlib import Path
from datetime import datetime, timezone, timedelta

# ── Config ──
MCP_CLI = str(Path(__file__).parent / "tradingview-mcp" / "src" / "cli" / "index.js")
SYMBOL = "MNQ1!"
TIMEFRAME = "1"  # 1 minute
SCREENSHOT_DIR = Path(__file__).parent / "trade_screenshots"

# Central Time offset (CT = UTC-5 for CDT)
CT_OFFSET = timedelta(hours=-5)

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


def ct_to_unix(ct_str):
    """Convert CT datetime string to unix timestamp."""
    dt = datetime.strptime(ct_str, "%Y-%m-%d %H:%M")
    # CT is UTC-5 (CDT in April)
    dt_utc = dt - CT_OFFSET
    return int(dt_utc.replace(tzinfo=timezone.utc).timestamp())


def run_cli(*args, timeout=30):
    """Run tradingview-mcp CLI command and return parsed result."""
    cmd = ["node", MCP_CLI] + list(args)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                                encoding='utf-8', errors='replace')
        stdout = (result.stdout or "").strip()
        stderr = (result.stderr or "").strip()
        if result.returncode != 0:
            print(f"  CLI error: {stderr or result.returncode}")
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
    result = run_cli("symbol", SYMBOL)
    print(f"  {result}")
    time.sleep(2)

    print(f"Setting timeframe to {TIMEFRAME}m...")
    result = run_cli("timeframe", TIMEFRAME)
    print(f"  {result}")
    time.sleep(2)


def get_ohlcv_bars(count=100):
    """Get visible OHLCV bars from the chart."""
    result = run_cli("ohlcv", "-n", str(count))
    if not result:
        return None
    # Try common response shapes
    if isinstance(result, dict):
        for key in ("bars", "data", "candles"):
            if key in result:
                val = result[key]
                if isinstance(val, list):
                    return val
                if isinstance(val, dict) and "bars" in val:
                    return val["bars"]
    if isinstance(result, list):
        return result
    return result


def scroll_to_date(date_str):
    """Scroll chart to a specific date. Format: YYYY-MM-DD HH:MM (CT)"""
    result = run_cli("scroll", date_str)
    return result


def set_visible_range(start_ct, end_ct):
    """Set the visible range using unix timestamps."""
    start_unix = ct_to_unix(start_ct)
    end_unix = ct_to_unix(end_ct)
    result = run_cli("range", "--from", str(start_unix), "--to", str(end_unix))
    return result


def capture_screenshot(filename, region="chart"):
    """Capture screenshot and save to file."""
    args = ["screenshot"]
    if region != "chart":
        args += ["-r", region]
    args += ["-o", str(filename).replace(".png", "")]

    result = run_cli(*args, timeout=15)
    if result and isinstance(result, dict):
        # Check if base64 image data returned
        img_b64 = result.get("image") or (result.get("data", {}) or {}).get("image")
        if img_b64:
            img_data = base64.b64decode(img_b64)
            with open(filename, "wb") as f:
                f.write(img_data)
            print(f"  Saved: {filename}")
            return True
        if "path" in result:
            print(f"  Screenshot saved by CLI: {result['path']}")
            return True
        if result.get("success"):
            print(f"  Screenshot taken (check CLI output dir)")
            return True
    print(f"  Screenshot result: {str(result)[:200]}")
    return False


def analyze_trade(trade, index):
    """Navigate to trade entry time and capture screenshot."""
    label = trade["label"]
    entry_time = trade["time"]
    side = trade["side"]
    entry_price = trade["entry"]

    print(f"\n{'='*60}")
    print(f"Trade #{index+1}: {label} -- {side} @ {entry_price}")
    print(f"{'='*60}")

    # Scroll to the trade time
    print(f"  Scrolling to {entry_time} CT...")
    scroll_to_date(entry_time)
    time.sleep(3)

    # Capture screenshot
    safe_label = label.replace(' ', '_').replace(':', '').replace('(', '').replace(')', '')
    filename = SCREENSHOT_DIR / f"trade_{index+1:02d}_{safe_label}.png"
    print(f"  Capturing screenshot...")
    capture_screenshot(str(filename))

    # Get OHLCV data for MAE analysis
    print(f"  Fetching bar data for MAE analysis...")
    bars = get_ohlcv_bars(60)

    if bars and isinstance(bars, list):
        calc_mae(bars, side, entry_price)
    else:
        print(f"  Could not get bar data: {type(bars)}")

    return bars


def calc_mae(bars, side, entry_price):
    """Calculate MAE from bar data."""
    if side == "Long":
        lows = []
        for b in bars:
            low = b.get("low") or b.get("l") or b.get("Low") or 0
            if low > 0:
                lows.append(low)
        if lows:
            worst = min(lows)
            mae = entry_price - worst
            print(f"  Lowest low in window: {worst}")
            print(f"  MAE (adverse excursion): {mae:.2f} pts (${mae * 2:.2f}/contract)")
    else:
        highs = []
        for b in bars:
            high = b.get("high") or b.get("h") or b.get("High") or 0
            if high > 0:
                highs.append(high)
        if highs:
            worst = max(highs)
            mae = worst - entry_price
            print(f"  Highest high in window: {worst}")
            print(f"  MAE (adverse excursion): {mae:.2f} pts (${mae * 2:.2f}/contract)")


def capture_full_session():
    """Capture the full session overview (11:45 PM Apr 6 to 2:20 PM Apr 7 CT)."""
    print(f"\n{'='*60}")
    print("Full Session Overview")
    print(f"{'='*60}")

    print("  Setting visible range for full session...")
    set_visible_range("2026-04-06 23:30", "2026-04-07 14:30")
    time.sleep(3)

    filename = SCREENSHOT_DIR / "00_full_session.png"
    print("  Capturing full session screenshot...")
    capture_screenshot(str(filename), region="full")


def main():
    SCREENSHOT_DIR.mkdir(exist_ok=True)

    # Check CLI exists
    if not Path(MCP_CLI).exists():
        print(f"ERROR: tradingview-mcp CLI not found at: {MCP_CLI}")
        print(f"Make sure tradingview-mcp is cloned in the project directory.")
        sys.exit(1)

    # Check TradingView connection
    print("Checking TradingView connection...")
    health = run_cli("status")
    if not health:
        print("ERROR: Cannot connect to TradingView Desktop on port 9222.")
        print("Make sure TradingView is running with --remote-debugging-port=9222")
        sys.exit(1)
    print(f"  Connected: {health}")

    # Setup chart
    setup_chart()

    # Capture full session overview
    capture_full_session()

    # Analyze each trade
    for i, trade in enumerate(TRADES):
        analyze_trade(trade, i)
        time.sleep(2)

    print(f"\n{'='*60}")
    print(f"Done! Screenshots saved to: {SCREENSHOT_DIR}")
    print(f"{'='*60}")
    print(f"\nKey trades to examine:")
    print(f"  - Trade #7 (5:30 AM Long, 33 min hold): How far did price dip before TP?")
    print(f"  - Trade #8 (8:21 AM Short, 18 sec): Clean entry or luck?")


if __name__ == "__main__":
    main()
