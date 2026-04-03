"""
Bridge to TradingView MCP — wraps CLI commands and direct CDP calls.

Supports two modes:
1. CLI mode: shells out to `node src/cli/index.js <command>`
2. CDP mode: direct HTTP/WebSocket to TradingView's debug port (faster)

CDP mode is preferred for replay loops where latency matters.
"""

import json
import subprocess
import urllib.request
import urllib.error
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class MCPResult:
    success: bool
    data: dict
    error: str = ""


class TVBridge:
    """Interface to TradingView via MCP CLI or direct CDP."""

    def __init__(self, cli_path="", cdp_host="localhost", cdp_port=9222):
        self.cli_path = cli_path
        self.cdp_host = cdp_host
        self.cdp_port = cdp_port
        self._ws_url = None

    # ── CDP direct methods (fast path) ──

    def _cdp_url(self, path="/json/list"):
        return f"http://{self.cdp_host}:{self.cdp_port}{path}"

    def cdp_available(self) -> bool:
        try:
            req = urllib.request.urlopen(self._cdp_url("/json/version"), timeout=3)
            return req.status == 200
        except (urllib.error.URLError, OSError):
            return False

    def _cdp_targets(self) -> list:
        try:
            resp = urllib.request.urlopen(self._cdp_url("/json/list"), timeout=5)
            return json.loads(resp.read())
        except (urllib.error.URLError, OSError, json.JSONDecodeError):
            return []

    def find_chart_target(self) -> dict | None:
        targets = self._cdp_targets()
        for t in targets:
            if t.get("type") == "page" and "tradingview.com/chart" in t.get("url", "").lower():
                return t
        for t in targets:
            if t.get("type") == "page" and "tradingview" in t.get("url", "").lower():
                return t
        return None

    # ── CLI methods ──

    def _run_cli(self, *args, timeout=30) -> MCPResult:
        if not self.cli_path:
            return MCPResult(success=False, data={}, error="MCP CLI path not configured")
        cmd = ["node", self.cli_path] + list(args)
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout,
                encoding='utf-8', errors='replace'
            )
            stderr = (result.stderr or "").strip()
            stdout = (result.stdout or "").strip()
            if result.returncode != 0:
                return MCPResult(
                    success=False, data={},
                    error=stderr or f"Exit code {result.returncode}"
                )
            if not stdout:
                return MCPResult(success=True, data={})
            try:
                data = json.loads(stdout)
                return MCPResult(success=data.get("success", True), data=data)
            except json.JSONDecodeError:
                return MCPResult(success=True, data={"raw": stdout})
        except subprocess.TimeoutExpired:
            return MCPResult(success=False, data={}, error="Command timed out")
        except FileNotFoundError:
            return MCPResult(success=False, data={}, error="Node.js not found")

    # ── Health ──

    def health_check(self) -> MCPResult:
        return self._run_cli("status")

    # ── Chart control ──

    def set_symbol(self, symbol: str) -> MCPResult:
        return self._run_cli("symbol", symbol)

    def set_timeframe(self, tf: str) -> MCPResult:
        return self._run_cli("timeframe", tf)

    def get_quote(self) -> MCPResult:
        return self._run_cli("quote")

    def get_state(self) -> MCPResult:
        return self._run_cli("state")

    # ── Data reading ──

    def get_ohlcv(self, count=100, summary=False) -> MCPResult:
        args = ["ohlcv"]
        if summary:
            args.append("--summary")
        if count != 100:
            args.extend(["--count", str(count)])
        return self._run_cli(*args)

    def get_study_values(self) -> MCPResult:
        return self._run_cli("values")

    def get_pine_labels(self, study_filter="", max_labels=50) -> MCPResult:
        args = ["data", "labels"]
        if study_filter:
            args.extend(["--filter", study_filter])
        if max_labels != 50:
            args.extend(["--max", str(max_labels)])
        return self._run_cli(*args)

    def get_pine_tables(self, study_filter="") -> MCPResult:
        args = ["data", "tables"]
        if study_filter:
            args.extend(["--filter", study_filter])
        return self._run_cli(*args)

    def get_pine_lines(self, study_filter="") -> MCPResult:
        args = ["data", "lines"]
        if study_filter:
            args.extend(["--filter", study_filter])
        return self._run_cli(*args)

    def get_pine_boxes(self, study_filter="") -> MCPResult:
        args = ["data", "boxes"]
        if study_filter:
            args.extend(["--filter", study_filter])
        return self._run_cli(*args)

    # ── Replay ──

    def replay_start(self, date="") -> MCPResult:
        args = ["replay", "start"]
        if date:
            args.extend(["--date", date])
        return self._run_cli(*args, timeout=15)

    def replay_step(self) -> MCPResult:
        return self._run_cli("replay", "step", timeout=10)

    def replay_autoplay(self, speed=None) -> MCPResult:
        args = ["replay", "autoplay"]
        if speed is not None:
            args.extend(["--speed", str(speed)])
        return self._run_cli(*args, timeout=10)

    def replay_stop(self) -> MCPResult:
        return self._run_cli("replay", "stop", timeout=10)

    def replay_status(self) -> MCPResult:
        return self._run_cli("replay", "status", timeout=10)

    def replay_trade(self, action: str) -> MCPResult:
        """Execute a replay trade: buy, sell, or close.

        Uses DOM clicks on TradingView's order panel since the replay API's
        buy()/sell() methods don't actually create trades.
        """
        return self._replay_trade_via_ui(action)

    def _replay_trade_via_ui(self, action: str) -> MCPResult:
        """Click Buy/Sell/Close in TradingView's order panel via DOM."""
        if action == "buy":
            return self._place_order_via_ui("Buy")
        elif action == "sell":
            return self._place_order_via_ui("Sell")
        elif action == "close":
            return self._close_position_via_ui()
        else:
            return MCPResult(success=False, data={}, error=f"Unknown action: {action}")

    def _ensure_trade_helper_loaded(self):
        """Load the trade helper JS into TradingView if not already loaded."""
        check = self._run_cli("ui", "eval", "typeof window._floop", timeout=5)
        if check.success and check.data.get("result") == "object":
            return True
        # Load the helper
        helper_path = Path(__file__).parent / "trade_helper.js"
        if not helper_path.exists():
            return False
        js_code = helper_path.read_text(encoding="utf-8")
        result = self._run_cli("ui", "eval", js_code, timeout=10)
        return result.success

    def _ensure_trade_panel_open(self):
        """Click the 'Trade' tab at the BOTTOM of TradingView."""
        self._ensure_trade_helper_loaded()
        result = self._run_cli("ui", "eval", "window._floop.openTradePanel()", timeout=10)
        if result.success and result.data.get("result") not in ("already_open",):
            time.sleep(0.5)
        return result

    def dismiss_dialogs(self):
        """Dismiss any popup dialogs like 'Leave current replay?'"""
        self._ensure_trade_helper_loaded()
        return self._run_cli("ui", "eval", "window._floop.dismissDialog()", timeout=5)

    def _place_order_via_ui(self, side: str) -> MCPResult:
        """Select side, switch to Market, click Place Order."""
        self._ensure_trade_helper_loaded()

        # Step 1: Make sure trade panel is open (with delay for DOM render)
        panel_result = self._run_cli("ui", "eval", "window._floop.openTradePanel()", timeout=10)
        panel_status = panel_result.data.get("result", "") if panel_result.success else ""

        if panel_status not in ("already_open",):
            time.sleep(0.8)  # Wait for panel to render

        # Step 2: Select side
        side_fn = "Buy" if side == "Buy" else "Sell"
        sel_result = self._run_cli("ui", "eval", f"window._floop.selectSide('{side_fn}')", timeout=10)
        sel_status = sel_result.data.get("result", "") if sel_result.success else ""

        if "not_found" in str(sel_status):
            # Panel might not have the Buy/Sell buttons — try opening the top Trade panel
            self._run_cli("ui", "eval",
                "document.querySelector('[data-name=trading-floating-toolbar], "
                "[id*=trading-panel-button]')?.click() || 'no_top_trade'",
                timeout=5)
            time.sleep(0.8)
            sel_result = self._run_cli("ui", "eval", f"window._floop.selectSide('{side_fn}')", timeout=10)
            sel_status = sel_result.data.get("result", "") if sel_result.success else ""

        if "not_found" in str(sel_status):
            return MCPResult(success=False, data={"panel": panel_status, "side": sel_status},
                             error=f"Could not find {side} selector")

        # Step 3: Select Market order type
        time.sleep(0.2)
        self._run_cli("ui", "eval", "window._floop.selectMarket()", timeout=10)

        # Step 4: Place order
        time.sleep(0.3)
        place_result = self._run_cli("ui", "eval", "window._floop.placeOrder()", timeout=10)
        place_status = place_result.data.get("result", "") if place_result.success else ""

        if "not_found" in str(place_status):
            return MCPResult(success=False, data={}, error="Place order button not found")

        return MCPResult(success=True, data={"action": side.lower(), "result": place_status})

    def _close_position_via_ui(self) -> MCPResult:
        """Close position via DOM."""
        self._ensure_trade_helper_loaded()
        result = self._run_cli("ui", "eval", "window._floop.close()", timeout=10)
        return MCPResult(success=True, data={"action": "close", "result": result.data.get("result", "")})


    # ── Screenshots ──

    def screenshot(self, region="chart") -> MCPResult:
        return self._run_cli("screenshot", "-r", region, timeout=15)

    # ── Pine Script ──

    def pine_get_source(self) -> MCPResult:
        return self._run_cli("pine", "get")

    def pine_get_errors(self) -> MCPResult:
        return self._run_cli("pine", "errors")

    def pine_get_console(self) -> MCPResult:
        return self._run_cli("pine", "console")

    # ── Strategy data ──

    def get_strategy_results(self) -> MCPResult:
        return self._run_cli("data", "strategy")

    def get_trades(self, max_trades=20) -> MCPResult:
        return self._run_cli("data", "trades", "--max", str(max_trades))

    def get_equity(self) -> MCPResult:
        return self._run_cli("data", "equity")
