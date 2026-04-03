"""
Web dashboard and API server for Floopbot replay testing.

Provides:
- Real-time dashboard UI showing position, P&L, signals, trades
- REST API for controlling replay (start/stop/arm/disarm)
- Executes trades directly in TradingView replay mode via replay_trade
- No external dependencies — uses only Python stdlib
"""

import json
import os
import sys
import threading
import time
from datetime import datetime
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, parse_qs

from .config import TradingConfig
from .mcp_bridge import TVBridge
from .signal_parser import SignalAggregator, FloopSignal, SignalSide, parse_tables, parse_study_values
from .paper_trader import PaperTrader, Trade

STATIC_DIR = Path(__file__).parent / "static"


class ReplayEngine:
    """
    Core engine that runs replay, reads signals, and executes trades
    in TradingView's replay mode via replay_trade.
    """

    def __init__(self, config: TradingConfig):
        self.config = config
        self.bridge = TVBridge(
            cli_path=config.mcp_cli_path,
            cdp_host=config.cdp_host,
            cdp_port=config.cdp_port,
        )
        self.paper = PaperTrader(config)
        self.signal_agg = SignalAggregator(config.floop_indicator_name)

        # State
        self.armed = False
        self.running = False
        self.replay_active = False
        self.bar_count = 0
        self.start_time = 0.0

        # Current data
        self.last_price = 0.0
        self.last_quote = {}
        self.last_signal: Optional[FloopSignal] = None
        self.position_side = "FLAT"
        self.position_entry = 0.0
        self.tv_position = None
        self.tv_pnl = 0.0
        self.table_data = {}
        self.signal_log = []  # last 50 signals
        self.trade_log = []  # last 50 trades
        self.errors = []

        # Thread
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    @property
    def status(self) -> dict:
        """Full status snapshot for the dashboard."""
        stats = self.paper.stats
        return {
            "armed": self.armed,
            "running": self.running,
            "replay_active": self.replay_active,
            "bar_count": self.bar_count,
            "elapsed": round(time.time() - self.start_time, 1) if self.start_time else 0,
            "last_price": self.last_price,
            "position": self.position_side,
            "position_entry": self.position_entry,
            "stop_price": round(self.paper.position.stop_price, 2),
            "trail_price": round(self.paper.position.trail_price, 2),
            "atr_at_entry": round(self.paper.position.atr_at_entry, 4),
            "bars_held": self.paper.position.bars_held,
            "high_water": round(self.paper.position.high_water, 2),
            "tv_position": self.tv_position,
            "tv_pnl": self.tv_pnl,
            "unrealized_pnl": round(self.paper.unrealized_pnl, 2),
            "daily_pnl": round(self.paper.daily_pnl, 2),
            "daily_trades": self.paper.daily_trades,
            "daily_wins": self.paper.daily_wins,
            "daily_losses": self.paper.daily_losses,
            "total_trades": stats.get("total_trades", 0),
            "total_pnl": stats.get("total_pnl", 0),
            "win_rate": stats.get("win_rate", 0),
            "wins": stats.get("wins", 0),
            "losses": stats.get("losses", 0),
            "profit_factor": stats.get("profit_factor", 0),
            "max_drawdown": stats.get("max_drawdown", 0),
            "avg_win": stats.get("avg_win", 0),
            "avg_loss": stats.get("avg_loss", 0),
            "symbol": self.config.symbol,
            "timeframe": self.config.timeframe,
            "atr_stop_multiplier": self.config.atr_stop_multiplier,
            "trail_distance_atr": self.config.trail_distance_atr,
            "trail_mode": self.config.trail_mode,
            "min_signal_strength": self.config.min_signal_strength,
            "max_daily_loss": self.config.max_daily_loss,
            "max_daily_trades": self.config.max_daily_trades,
            "signal_strength": self.table_data.get("signal_strength_value", "—"),
            "quality": self.table_data.get("quality", ""),
            "bias": self.table_data.get("bias", "—"),
            "last_signal": {
                "side": self.last_signal.side.value if self.last_signal else "—",
                "price": self.last_signal.price if self.last_signal else 0,
                "strength": self.last_signal.signal_strength if self.last_signal else 0,
            } if self.last_signal else None,
            "signal_log": self.signal_log[-20:],
            "trade_log": self.trade_log[-20:],
            "errors": self.errors[-10:],
            "timestamp": datetime.now().strftime("%H:%M:%S"),
        }

    def check_connection(self) -> dict:
        """Check TradingView connection."""
        result = self.bridge.health_check()
        return result.data if result.success else {"error": result.error}

    def start_replay(self, date: str = "") -> bool:
        """Start TradingView replay mode."""
        # Don't stop existing replay — just start fresh
        result = self.bridge.replay_start(date=date or self.config.replay_start_date)
        if result.success:
            self.replay_active = True
            self.signal_agg.reset()
            self._log_signal("SYSTEM", 0, "Replay started")
            return True
        self.errors.append(f"Replay start failed: {result.error}")
        return False

    def stop_replay(self):
        """Stop replay mode."""
        if not self.paper.is_flat:
            self._execute_close("manual", closing_side=self.position_side)
            trade = self.paper.flatten(self.last_price, self.last_bar_time)
            if trade:
                self._log_trade(trade)
        self.bridge.replay_stop()
        self.replay_active = False
        self._log_signal("SYSTEM", 0, "Replay stopped")

    def arm(self):
        self.armed = True
        self._log_signal("SYSTEM", 0, "ARMED — auto-trading enabled")

    def disarm(self):
        self.armed = False
        self._log_signal("SYSTEM", 0, "DISARMED — auto-trading paused")

    def flatten(self):
        """Force close any open position."""
        if not self.paper.is_flat:
            self._execute_close("manual_flatten", closing_side=self.position_side)
            trade = self.paper.flatten(self.last_price, self.last_bar_time)
            if trade:
                self._log_trade(trade)

    def start_loop(self):
        """Start the main polling loop in a background thread."""
        if self.running:
            return
        self._stop_event.clear()
        self.running = True
        self.start_time = time.time()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop_loop(self):
        """Stop the polling loop."""
        self._stop_event.set()
        self.running = False
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

    def run_backtest(self, speed: int = 0):
        """
        One-click backtest: arm, start autoplay, monitor for signals.
        This is the main workflow the user wants.
        """
        # Arm the bot
        self.armed = True

        # Dismiss any lingering dialogs
        self.bridge.dismiss_dialogs()

        # Check if we're already in replay mode
        status = self.bridge.replay_status()
        already_in_replay = (status.success and status.data.get("is_replay_started"))
        if already_in_replay:
            self.replay_active = True
            self._log_signal("SYSTEM", 0, "Replay already running")
        else:
            self._log_signal("SYSTEM", 0, "Starting replay mode...")
            if not self.start_replay():
                self.bridge.dismiss_dialogs()
                time.sleep(1)
                if not self.start_replay():
                    return False

        # Wait for replay UI to settle, then click "Trade" tab at bottom
        time.sleep(1)
        self.bridge._ensure_trade_helper_loaded()
        trade_result = self.bridge._ensure_trade_panel_open()
        trade_status = trade_result.data.get("result", "?") if trade_result.success else "failed"
        self._log_signal("SYSTEM", 0, f"Trade panel: {trade_status}")
        if "clicked" in str(trade_status):
            time.sleep(1)  # Wait for order panel to render

        # Start TradingView autoplay (fast-forward)
        result = self.bridge.replay_autoplay(speed=speed)
        if result.success:
            self._log_signal("SYSTEM", 0, f"Autoplay started (speed={speed})")
        else:
            self._log_signal("SYSTEM", 0, f"Autoplay failed: {result.error} — press play manually")

        # Start monitoring loop
        self.start_loop()
        return True

    def step_once(self):
        """Advance one bar and process."""
        result = self.bridge.replay_step()
        if not result.success:
            self.errors.append(f"Step failed: {result.error}")
            return
        time.sleep(0.15)
        self._poll_and_process()
        self.bar_count += 1

    def _run_loop(self):
        """
        Background monitoring loop.

        In monitor mode (default): polls TradingView every 200ms for new
        prices and signals. TradingView controls playback speed (user
        presses play/fast-forward). The bot just watches and trades.

        In step mode: bot controls playback, advancing one bar at a time.
        """
        self._log_signal("SYSTEM", 0, "Monitoring started — watching for signals...")
        last_price = 0.0

        while not self._stop_event.is_set():
            try:
                if self.config.step_mode:
                    result = self.bridge.replay_step()
                    if not result.success:
                        status = self.bridge.replay_status()
                        if status.success and not status.data.get("is_replay_started"):
                            self.replay_active = False
                            self._log_signal("SYSTEM", 0, "Replay ended — no more bars")
                            break
                        time.sleep(0.5)
                        continue
                    time.sleep(0.1)

                self._poll_and_process()

                # Only count as new bar if price changed
                if self.last_price != last_price and self.last_price > 0:
                    last_price = self.last_price
                    self.bar_count += 1

                if self.config.bars_to_run > 0 and self.bar_count >= self.config.bars_to_run:
                    self._log_signal("SYSTEM", 0, f"Bar limit reached ({self.config.bars_to_run})")
                    break

                # Poll interval — fast enough to catch signals, light enough to not lag
                time.sleep(0.2)

            except Exception as e:
                self.errors.append(str(e))
                time.sleep(1)

        self.running = False

    def _poll_and_process(self):
        """Read current state, detect signals, manage trades."""
        # Get quote
        quote = self.bridge.get_quote()
        if not quote.success:
            return
        self.last_quote = quote.data
        self.last_price = quote.data.get("close", 0) or quote.data.get("last", 0)
        high = quote.data.get("high", self.last_price)
        low = quote.data.get("low", self.last_price)
        bar_time = str(quote.data.get("time", ""))

        if self.last_price <= 0:
            return

        # Process bar through paper trader (check stops)
        # Save position side BEFORE on_bar() closes it internally
        pre_bar_side = self.position_side
        stopped = self.paper.on_bar(high, low, self.last_price, bar_time)
        if stopped:
            self._execute_close(stopped.exit_reason, closing_side=pre_bar_side)
            self._log_trade(stopped)
        elif not self.paper.is_flat and self.bar_count % 5 == 0:
            # Redraw stop lines periodically to track trailing stop movement
            self._draw_stop_lines()

        # Read replay status for TV position/PnL
        rep_status = self.bridge.replay_status()
        if rep_status.success:
            self.tv_position = rep_status.data.get("position")
            self.tv_pnl = rep_status.data.get("realized_pnl", 0) or 0

        # Read FLOOP signals
        labels = self.bridge.get_pine_labels(study_filter=self.config.floop_indicator_name)
        if not labels.success:
            # Try without filter in case indicator name doesn't match
            labels = self.bridge.get_pine_labels()

        if labels.success:
            # Debug: log raw label data on first successful read
            if self.bar_count <= 1 and labels.data:
                studies = labels.data.get("studies", [])
                study_names = [s.get("name", "?") for s in studies]
                total_labels = sum(len(s.get("labels", [])) for s in studies)
                self._log_signal("DEBUG", 0,
                                 f"Labels: {total_labels} from studies: {study_names}")
                # Log first few label texts for debugging
                for s in studies:
                    for lbl in s.get("labels", [])[:3]:
                        self._log_signal("DEBUG", 0,
                                         f"  Label: {lbl.get('text', '?')} @ {lbl.get('price', 0)}")

            signal = self.signal_agg.check_new_signal(labels.data)
            if signal and signal.is_valid:
                self.last_signal = signal

                # Enrich with table data and study values
                tables = self.bridge.get_pine_tables(study_filter=self.config.floop_indicator_name)
                if tables.success:
                    self.table_data = parse_tables(tables.data, self.config.floop_indicator_name)
                    if signal.signal_strength == 0 and "signal_strength_value" in self.table_data:
                        signal.signal_strength = self.table_data["signal_strength_value"]

                # Get ATR from study values if not in signal text
                if signal.atr <= 0:
                    values = self.bridge.get_study_values()
                    if values.success:
                        study_vals = parse_study_values(values.data, self.config.floop_indicator_name)
                        # Look for ATR plot value
                        for key in ("ATR", "atr", "ATR Value", "atr_value"):
                            if key in study_vals and study_vals[key] > 0:
                                signal.atr = float(study_vals[key])
                                break
                    # Fallback: derive ATR from table "ATR 0.04%" and current price
                    if signal.atr <= 0 and "atr_pct" in self.table_data and self.last_price > 0:
                        signal.atr = self.last_price * (self.table_data["atr_pct"] / 100.0)

                # Last resort: calculate ATR from OHLCV bars
                if signal.atr <= 0:
                    signal.atr = self._calc_atr_from_ohlcv()

                self._log_signal(signal.side.value, signal.price,
                                 f"Str: {signal.signal_strength} ATR: {signal.atr:.2f}" if signal.atr > 0
                                 else f"Str: {signal.signal_strength} (no ATR)")

                # Execute if armed
                if self.armed:
                    self._process_signal(signal, bar_time)

    def _process_signal(self, signal: FloopSignal, bar_time: str):
        """
        Process signal and execute trades in TradingView replay.

        Replicates the actual Floopbot entry gates from main.py:
        1. Armed check (handled by caller)
        2. Daily loss limit check
        3. Signal strength >= min_signal_strength
        4. Max trades per day
        5. Same-direction skip (already in position same side)
        6. Opposite direction → reverse (close + open)
        """
        price = self.last_price

        # ── EXIT signals bypass all entry gates ──
        if signal.is_exit:
            if not self.paper.is_flat:
                self._execute_close("signal_exit", closing_side=self.position_side)
                trade = self.paper.on_signal(signal, current_price=price, bar_time=bar_time)
                if trade:
                    self._log_trade(trade)
            return

        # ── Entry gate 1: Daily loss limit ──
        if abs(self.paper.daily_pnl) >= self.config.max_daily_loss:
            self._log_signal("SKIP", price,
                             f"Daily loss limit hit (${self.paper.daily_pnl:.0f} / -${self.config.max_daily_loss:.0f})")
            return

        # ── Entry gate 2: Signal strength filter ──
        if signal.signal_strength > 0 and signal.signal_strength < self.config.min_signal_strength:
            self._log_signal("SKIP", price,
                             f"Strength {signal.signal_strength} < {self.config.min_signal_strength}")
            return

        # ── Entry gate 3: Max trades per day ──
        if self.paper.daily_trades >= self.config.max_daily_trades:
            self._log_signal("SKIP", price,
                             f"Max daily trades reached ({self.paper.daily_trades}/{self.config.max_daily_trades})")
            return

        # ── Entry gate 4: Same-direction skip ──
        if signal.side == SignalSide.LONG and self.paper.is_long:
            self._log_signal("SKIP", price, "Already LONG — duplicate direction")
            return
        if signal.side == SignalSide.SHORT and self.paper.is_short:
            self._log_signal("SKIP", price, "Already SHORT — duplicate direction")
            return

        # ── Reversal: close opposite, then open new ──
        if signal.side == SignalSide.LONG:
            if self.paper.is_short:
                self._execute_close("signal_reverse", closing_side="SHORT")
                trade = self.paper.on_signal(
                    FloopSignal(side=SignalSide.EXIT), current_price=price, bar_time=bar_time)
                if trade:
                    self._log_trade(trade)
            if self.paper.is_flat:
                self._execute_buy(signal, price, bar_time)

        elif signal.side == SignalSide.SHORT:
            if self.paper.is_long:
                self._execute_close("signal_reverse", closing_side="LONG")
                trade = self.paper.on_signal(
                    FloopSignal(side=SignalSide.EXIT), current_price=price, bar_time=bar_time)
                if trade:
                    self._log_trade(trade)
            if self.paper.is_flat:
                self._execute_sell(signal, price, bar_time)

    def _pause_autoplay(self):
        """Pause TradingView autoplay before executing a trade."""
        status = self.bridge.replay_status()
        if status.success and status.data.get("is_autoplay_started"):
            self.bridge.replay_autoplay()  # toggle off
            time.sleep(0.3)
            return True
        return False

    def _resume_autoplay(self):
        """Resume TradingView autoplay after executing a trade."""
        status = self.bridge.replay_status()
        if status.success and not status.data.get("is_autoplay_started"):
            self.bridge.replay_autoplay()  # toggle on

    def _execute_buy(self, signal: FloopSignal, price: float, bar_time: str):
        """Execute a buy in TradingView replay and track internally."""
        was_autoplaying = self._pause_autoplay()
        result = self.bridge.replay_trade("buy")
        self._log_signal("DEBUG", price,
                         f"replay_trade(buy) → success={result.success} data={result.data} err={result.error}")
        if result.success:
            self.paper.on_signal(signal, current_price=price, bar_time=bar_time)
            self.position_side = "LONG"
            self.position_entry = price
            stop = self.paper.position.stop_price
            atr = self.paper.position.atr_at_entry
            self._log_signal("BUY", price,
                             f"Long @ {price:.2f} | ATR={atr:.2f} Stop={stop:.2f}" if stop > 0
                             else f"Long @ {price:.2f} | NO ATR — no stop set!")
            self._draw_stop_lines()
        else:
            self.errors.append(f"Buy failed: {result.error}")
        if was_autoplaying:
            time.sleep(0.2)
            self._resume_autoplay()

    def _execute_sell(self, signal: FloopSignal, price: float, bar_time: str):
        """Execute a sell in TradingView replay and track internally."""
        was_autoplaying = self._pause_autoplay()
        result = self.bridge.replay_trade("sell")
        self._log_signal("DEBUG", price,
                         f"replay_trade(sell) → success={result.success} data={result.data} err={result.error}")
        if result.success:
            self.paper.on_signal(signal, current_price=price, bar_time=bar_time)
            self.position_side = "SHORT"
            self.position_entry = price
            stop = self.paper.position.stop_price
            atr = self.paper.position.atr_at_entry
            self._log_signal("SELL", price,
                             f"Short @ {price:.2f} | ATR={atr:.2f} Stop={stop:.2f}" if stop > 0
                             else f"Short @ {price:.2f} | NO ATR — no stop set!")
            self._draw_stop_lines()
        else:
            self.errors.append(f"Sell failed: {result.error}")
        if was_autoplaying:
            time.sleep(0.2)
            self._resume_autoplay()

    def _execute_close(self, reason: str, closing_side: str = ""):
        """Close position in TradingView replay by placing the opposite trade."""
        side = closing_side or self.position_side
        if side == "FLAT":
            return  # nothing to close

        was_autoplaying = self._pause_autoplay()

        # In TradingView replay, close = opposite trade (sell to close long, buy to close short)
        if side == "LONG":
            result = self.bridge.replay_trade("sell")
            action = "sell-to-close"
        elif side == "SHORT":
            result = self.bridge.replay_trade("buy")
            action = "buy-to-close"
        else:
            result = self.bridge.replay_trade("close")
            action = "close"

        self._log_signal("DEBUG", self.last_price,
                         f"replay_trade({action}) → success={result.success} data={result.data} err={result.error}")
        if result.success:
            self.position_side = "FLAT"
            self.position_entry = 0.0
            self._log_signal("CLOSE", self.last_price,
                             f"{side} closed @ {self.last_price:.2f}: {reason}")
            self._clear_stop_lines()
        else:
            self.errors.append(f"Close failed ({action}): {result.error}")
        if was_autoplaying:
            time.sleep(0.2)
            self._resume_autoplay()

    def _calc_atr_from_ohlcv(self, period: int = 14) -> float:
        """Calculate ATR from recent OHLCV bars as fallback when indicator ATR unavailable."""
        try:
            ohlcv = self.bridge.get_ohlcv(count=period + 5)
            if not ohlcv.success:
                return 0.0
            bars = ohlcv.data.get("bars", ohlcv.data.get("data", []))
            if not bars or len(bars) < 2:
                return 0.0

            true_ranges = []
            for i in range(1, len(bars)):
                h = bars[i].get("high", 0)
                l = bars[i].get("low", 0)
                prev_c = bars[i - 1].get("close", 0)
                if h == 0 or l == 0 or prev_c == 0:
                    continue
                tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
                true_ranges.append(tr)

            if not true_ranges:
                return 0.0
            return sum(true_ranges[-period:]) / min(len(true_ranges), period)
        except Exception:
            return 0.0

    def _draw_stop_lines(self):
        """Draw stop/trail horizontal lines on TradingView chart via CDP."""
        if self.paper.is_flat:
            self._clear_stop_lines()
            return

        stop = self.paper.position.stop_price
        trail = self.paper.position.trail_price
        entry = self.paper.position.entry_price

        js = """
        (function() {
            // Remove old floop lines
            var old = document.querySelectorAll('[data-floop-line]');
            old.forEach(function(el) { el.remove(); });

            var chart = document.querySelector('.chart-markup-table');
            if (!chart) return 'no_chart';

            var pane = chart.closest('[class*=pane]') || chart.parentElement;
            var rect = chart.getBoundingClientRect();

            function priceToY(price) {
                // Use TradingView's price scale to convert price to Y coordinate
                var scale = document.querySelector('[class*=price-axis] [class*=pane]') ||
                            document.querySelector('[class*=priceAxis]');
                if (!scale) return -1;
                var labels = scale.querySelectorAll('[class*=label]');
                var prices = [];
                labels.forEach(function(l) {
                    var val = parseFloat(l.textContent.replace(/,/g, ''));
                    if (!isNaN(val)) {
                        var r = l.getBoundingClientRect();
                        prices.push({price: val, y: r.top + r.height/2});
                    }
                });
                if (prices.length < 2) return -1;
                prices.sort(function(a,b) { return a.price - b.price; });
                var p1 = prices[0], p2 = prices[prices.length-1];
                var pixPerPoint = (p1.y - p2.y) / (p2.price - p1.price);
                return p2.y + (p2.price - price) * pixPerPoint;
            }

            function drawLine(price, color, label) {
                if (price <= 0) return;
                var y = priceToY(price);
                if (y < 0) return;
                y = y - rect.top;
                var line = document.createElement('div');
                line.setAttribute('data-floop-line', label);
                line.style.cssText = 'position:absolute;left:0;right:60px;height:1px;' +
                    'background:' + color + ';top:' + y + 'px;z-index:5;pointer-events:none;' +
                    'border-top:1px dashed ' + color + ';opacity:0.8;';
                var tag = document.createElement('div');
                tag.style.cssText = 'position:absolute;right:0;top:-8px;background:' + color +
                    ';color:#fff;font-size:10px;padding:1px 4px;border-radius:2px;font-weight:bold;';
                tag.textContent = label + ' ' + price.toFixed(2);
                line.appendChild(tag);
                chart.appendChild(line);
            }

            drawLine(ENTRY_PRICE, '#3b82f6', 'ENTRY');
            drawLine(STOP_PRICE, '#ef4444', 'SL');
            drawLine(TRAIL_PRICE, '#eab308', 'TRAIL');
            return 'lines_drawn';
        })()
        """.replace("ENTRY_PRICE", str(entry)).replace("STOP_PRICE", str(stop)).replace("TRAIL_PRICE", str(trail))

        self.bridge._run_cli("ui", "eval", js, timeout=5)

    def _clear_stop_lines(self):
        """Remove stop/trail lines from TradingView chart."""
        js = """
        (function() {
            var old = document.querySelectorAll('[data-floop-line]');
            old.forEach(function(el) { el.remove(); });
            return 'cleared';
        })()
        """
        self.bridge._run_cli("ui", "eval", js, timeout=5)

    def _log_signal(self, side: str, price: float, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        entry = {"time": ts, "side": side, "price": round(price, 2), "msg": msg}
        self.signal_log.append(entry)
        if len(self.signal_log) > 100:
            self.signal_log = self.signal_log[-100:]

    def _log_trade(self, trade: Trade):
        entry = {
            "id": trade.trade_id,
            "side": trade.side,
            "entry": trade.entry_price,
            "exit": trade.exit_price,
            "pnl": trade.pnl_dollars,
            "ticks": trade.pnl_ticks,
            "reason": trade.exit_reason,
            "bars": trade.bars_held,
        }
        self.trade_log.append(entry)
        if len(self.trade_log) > 100:
            self.trade_log = self.trade_log[-100:]


class DashboardHandler(SimpleHTTPRequestHandler):
    """HTTP handler for dashboard and API."""

    engine: ReplayEngine = None  # set by server

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # API endpoints
        if path == "/api/status":
            self._json_response(self.engine.status)
        elif path == "/api/check":
            self._json_response(self.engine.check_connection())
        elif path == "/":
            self._serve_file("index.html", "text/html")
        elif path.startswith("/static/"):
            filename = path[8:]  # strip /static/
            self._serve_file(filename)
        else:
            self.send_error(404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length else b""

        try:
            data = json.loads(body) if body else {}
        except json.JSONDecodeError:
            data = {}

        if path == "/api/arm":
            self.engine.arm()
            self._json_response({"ok": True})
        elif path == "/api/disarm":
            self.engine.disarm()
            self._json_response({"ok": True})
        elif path == "/api/flatten":
            self.engine.flatten()
            self._json_response({"ok": True})
        elif path == "/api/start-replay":
            date = data.get("date", "")
            ok = self.engine.start_replay(date=date)
            self._json_response({"ok": ok, "errors": self.engine.errors[-3:]})
        elif path == "/api/stop-replay":
            self.engine.stop_replay()
            self._json_response({"ok": True})
        elif path == "/api/run-backtest":
            speed = data.get("speed", 0)
            ok = self.engine.run_backtest(speed=speed)
            self._json_response({"ok": ok, "errors": self.engine.errors[-3:]})
        elif path == "/api/start-loop":
            self.engine.start_loop()
            self._json_response({"ok": True})
        elif path == "/api/stop-loop":
            self.engine.stop_loop()
            self._json_response({"ok": True})
        elif path == "/api/step":
            self.engine.step_once()
            self._json_response({"ok": True, "bar_count": self.engine.bar_count, "errors": self.engine.errors[-3:]})
        elif path == "/api/autoplay":
            speed = data.get("speed", 0)
            result = self.engine.bridge.replay_autoplay(speed=speed)
            self._json_response({"ok": result.success})
        elif path == "/api/config":
            # Update config values
            for key in ["min_signal_strength", "atr_stop_multiplier",
                        "trail_distance_atr", "max_daily_loss", "max_daily_trades"]:
                if key in data:
                    setattr(self.engine.config, key, data[key])
                    setattr(self.engine.paper.config, key, data[key])
            self._json_response({"ok": True})
        else:
            self.send_error(404)

    def _json_response(self, data: dict, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _serve_file(self, filename: str, content_type: str = None):
        filepath = STATIC_DIR / filename
        if not filepath.exists():
            self.send_error(404)
            return
        content = filepath.read_bytes()
        if not content_type:
            if filename.endswith(".html"):
                content_type = "text/html"
            elif filename.endswith(".js"):
                content_type = "application/javascript"
            elif filename.endswith(".css"):
                content_type = "text/css"
            else:
                content_type = "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", len(content))
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, format, *args):
        pass  # suppress request logs


def run_dashboard(config: TradingConfig = None, port: int = 8082):
    """Start the dashboard server."""
    config = config or TradingConfig.load()
    engine = ReplayEngine(config)

    DashboardHandler.engine = engine

    server = HTTPServer(("0.0.0.0", port), DashboardHandler)
    print(f"Floopbot Dashboard running at http://localhost:{port}")
    print(f"Symbol: {config.symbol} | TF: {config.timeframe}")
    print(f"Press Ctrl+C to stop")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        engine.stop_loop()
        try:
            engine.bridge.replay_stop()
        except Exception:
            pass
        engine.replay_active = False
        server.shutdown()
