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
        """Execute a replay trade: buy, sell, or close."""
        return self._run_cli("replay", "trade", action, timeout=10)

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
