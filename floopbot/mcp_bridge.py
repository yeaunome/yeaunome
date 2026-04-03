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

    def _ensure_trade_panel_open(self):
        """Click the 'Trade' tab at the BOTTOM of TradingView to open the order panel.

        Must be careful NOT to click the top-right 'Trade' button which
        opens broker connection and can trigger 'Leave replay?' dialog.
        """
        js_open_trade = (
            '(function() {'
            '  // First check if order panel is already visible'
            '  var orderPanel = document.querySelector("[class*=orderWidget], [class*=orderTicket], [class*=orderPanel]");'
            '  if (orderPanel && orderPanel.offsetParent) return "already_open";'
            '  // Find the Trade tab in the BOTTOM widget bar only'
            '  var bottomBar = document.querySelector("[class*=bottom-widgetbar], [class*=layout__area--bottom]");'
            '  if (bottomBar) {'
            '    var tabs = bottomBar.querySelectorAll("button, [class*=tab], [role=tab]");'
            '    for (var i = 0; i < tabs.length; i++) {'
            '      var text = (tabs[i].textContent || "").trim();'
            '      if (/^Trade$/i.test(text) && tabs[i].offsetParent !== null) {'
            '        tabs[i].click();'
            '        return "trade_tab_clicked";'
            '      }'
            '    }'
            '  }'
            '  return "trade_tab_not_found";'
            '})()'
        )
        result = self._run_cli("ui", "eval", js_open_trade, timeout=10)
        if result.success and result.data.get("result") != "already_open":
            time.sleep(0.5)
        return result

    def dismiss_dialogs(self):
        """Dismiss any popup dialogs like 'Leave current replay?'"""
        js_dismiss = (
            '(function() {'
            '  var btns = document.querySelectorAll("button");'
            '  for (var i = 0; i < btns.length; i++) {'
            '    var text = (btns[i].textContent || "").trim();'
            '    if (/^Stay$/i.test(text) && btns[i].offsetParent !== null) {'
            '      btns[i].click();'
            '      return "dismissed_stay";'
            '    }'
            '  }'
            '  return "no_dialog";'
            '})()'
        )
        return self._run_cli("ui", "eval", js_dismiss, timeout=5)

    def _place_order_via_ui(self, side: str) -> MCPResult:
        """Select side, switch to Market, click Place Order."""
        # Step 0: Ensure the Trade panel is open
        self._ensure_trade_panel_open()

        # Step 1: Click the Buy or Sell side selector
        side_lower = side.lower()
        js_select_side = (
            '(function() {'
            '  // Search within order/trading panels for Buy/Sell text'
            '  var containers = document.querySelectorAll("[class*=order], [class*=trading], [class*=ticket]");'
            '  for (var c = 0; c < containers.length; c++) {'
            '    var els = containers[c].querySelectorAll("*");'
            '    for (var i = 0; i < els.length; i++) {'
            '      var e = els[i];'
            '      if (!e.offsetParent) continue;'
            '      var text = (e.textContent || "").trim();'
            '      // Match exact "Buy" or "Sell", or "Buy" followed by price like "Buy15,160.25"'
            f'      if (/^{side}$/i.test(text) || /^{side}[0-9,.\\s]/i.test(text)) {{'
            '        // Prefer leaf nodes or nodes with minimal children'
            '        if (e.children.length <= 2) {'
            '          e.click();'
            f'          return "selected_{side_lower}: " + e.tagName + " " + text.substring(0,20);'
            '        }'
            '      }'
            '    }'
            '  }'
            '  // Fallback: search everywhere'
            '  var all = document.querySelectorAll("span, div, button, a");'
            '  for (var i = 0; i < all.length; i++) {'
            '    var e = all[i];'
            '    if (!e.offsetParent) continue;'
            '    var ownText = "";'
            '    for (var j = 0; j < e.childNodes.length; j++) {'
            '      if (e.childNodes[j].nodeType === 3) ownText += e.childNodes[j].textContent;'
            '    }'
            '    ownText = ownText.trim();'
            f'    if (/^{side}$/i.test(ownText)) {{'
            '      e.click();'
            f'      return "selected_{side_lower}_fallback: " + e.tagName;'
            '    }'
            '  }'
            f'  return "no_{side_lower}_element";'
            '})()'
        )
        result1 = self._run_cli("ui", "eval", js_select_side, timeout=10)
        if not result1.success:
            return result1
        side_result = result1.data.get("result", "")
        if "no_" in str(side_result):
            return MCPResult(success=False, data={}, error=f"Could not find {side} selector in order panel")

        # Step 2: Click Market order type tab
        js_market = (
            '(function() {'
            '  var tabs = document.querySelectorAll("button, [class*=tab]");'
            '  for (var i = 0; i < tabs.length; i++) {'
            '    if (/^Market$/i.test(tabs[i].textContent.trim()) && tabs[i].offsetParent !== null) {'
            '      tabs[i].click();'
            '      return "market_selected";'
            '    }'
            '  }'
            '  return "market_not_found";'
            '})()'
        )
        result2 = self._run_cli("ui", "eval", js_market, timeout=10)

        # Step 3: Click Place Order button
        time.sleep(0.3)
        js_place = (
            '(function() {'
            '  var btn = document.querySelector("[data-name=place-and-modify-button]");'
            '  if (btn && btn.offsetParent !== null) {'
            '    btn.click();'
            '    return "order_placed";'
            '  }'
            '  return "place_button_not_found";'
            '})()'
        )
        result3 = self._run_cli("ui", "eval", js_place, timeout=10)
        if not result3.success:
            return result3
        place_result = result3.data.get("result", "")
        if place_result == "place_button_not_found":
            return MCPResult(success=False, data={}, error="Place order button not found")

        return MCPResult(success=True, data={"action": side.lower(), "result": "order_placed"})

    def _close_position_via_ui(self) -> MCPResult:
        """Close position by clicking the close/flatten button, or reversing."""
        self._ensure_trade_panel_open()
        # Try to find a close/flatten button
        js_close = (
            '(function() {'
            '  var btns = document.querySelectorAll("button, [class*=close], [class*=flatten]");'
            '  for (var i = 0; i < btns.length; i++) {'
            '    var text = (btns[i].textContent || "").trim();'
            '    if (/^close|^flatten|close position/i.test(text) && btns[i].offsetParent !== null) {'
            '      btns[i].click();'
            '      return "closed: " + text.substring(0, 30);'
            '    }'
            '  }'
            '  return "no_close_button";'
            '})()'
        )
        result = self._run_cli("ui", "eval", js_close, timeout=10)
        if result.success and result.data.get("result", "").startswith("closed"):
            return MCPResult(success=True, data={"action": "close", "result": result.data["result"]})

        # Fallback: try the API close
        result2 = self._run_cli("ui", "eval",
            'window.TradingViewApi._replayApi.closePosition(); "api_close_called"',
            timeout=10)
        return MCPResult(success=True, data={"action": "close", "result": "api_fallback"})


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
