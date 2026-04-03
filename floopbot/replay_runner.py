"""
Replay test orchestrator for Floopbot.

Controls TradingView's replay mode, reads FLOOP Pro signals,
feeds them to the paper trading engine, and generates reports.

Two modes:
1. Step mode: advance one bar at a time (slower, more precise)
2. Autoplay mode: let replay run, poll for signals (faster, may miss signals)
"""

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from .config import TradingConfig
from .mcp_bridge import TVBridge
from .signal_parser import SignalAggregator, parse_labels, parse_study_values, parse_tables
from .paper_trader import PaperTrader, Trade
from .report import ReportGenerator


class ReplayRunner:
    """
    Main orchestrator for automated replay testing.

    Lifecycle:
        runner = ReplayRunner(config)
        runner.setup()         # verify connection, set symbol/timeframe
        runner.start_replay()  # enter replay mode
        runner.run()           # main loop: step/poll -> read signals -> trade
        runner.stop()          # exit replay, generate report
    """

    def __init__(self, config: TradingConfig = None):
        self.config = config or TradingConfig.load()
        self.bridge = TVBridge(
            cli_path=self.config.mcp_cli_path,
            cdp_host=self.config.cdp_host,
            cdp_port=self.config.cdp_port,
        )
        self.trader = PaperTrader(self.config)
        self.signal_agg = SignalAggregator(self.config.floop_indicator_name)
        self.report = ReportGenerator(self.config)

        # Run state
        self.running = False
        self.bar_count = 0
        self.start_time = 0.0
        self.errors = []
        self._log_file = None

    def log(self, msg: str, level: str = "INFO"):
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] [{level}] {msg}"
        print(line, file=sys.stderr)
        if self._log_file:
            self._log_file.write(line + "\n")
            self._log_file.flush()

    def setup(self) -> bool:
        """Verify connection and prepare chart."""
        self.log("Checking TradingView connection...")
        health = self.bridge.health_check()
        if not health.success:
            self.log(f"Connection failed: {health.error}", "ERROR")
            return False

        self.log(f"Connected: {json.dumps(health.data, indent=2)}")

        # Set symbol and timeframe
        if self.config.symbol:
            self.log(f"Setting symbol to {self.config.symbol}")
            result = self.bridge.set_symbol(self.config.symbol)
            if not result.success:
                self.log(f"Failed to set symbol: {result.error}", "WARN")
            time.sleep(1)

        if self.config.timeframe:
            self.log(f"Setting timeframe to {self.config.timeframe}")
            result = self.bridge.set_timeframe(self.config.timeframe)
            if not result.success:
                self.log(f"Failed to set timeframe: {result.error}", "WARN")
            time.sleep(1)

        # Verify FLOOP Pro is on chart
        self.log("Checking for FLOOP Pro indicator...")
        values = self.bridge.get_study_values()
        if values.success:
            studies = values.data.get("studies", [])
            floop_found = any(
                self.config.floop_indicator_name.lower() in s.get("name", "").lower()
                for s in studies
            )
            if floop_found:
                self.log("FLOOP Pro indicator found on chart")
            else:
                study_names = [s.get("name", "") for s in studies]
                self.log(f"FLOOP Pro not found. Studies on chart: {study_names}", "WARN")
                self.log("Signals will be read from labels/tables instead", "WARN")

        # Create output directory
        output_dir = Path(self.config.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Open log file
        log_path = output_dir / f"replay_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        self._log_file = open(log_path, "w")
        self.log(f"Logging to {log_path}")

        return True

    def start_replay(self) -> bool:
        """Enter replay mode."""
        self.log("Starting replay mode...")

        # Stop any existing replay first
        self.bridge.replay_stop()
        time.sleep(1)

        result = self.bridge.replay_start(date=self.config.replay_start_date)
        if not result.success:
            self.log(f"Failed to start replay: {result.error}", "ERROR")
            return False

        self.log(f"Replay started: {json.dumps(result.data)}")
        time.sleep(1)

        # Read initial state
        self._read_initial_state()
        return True

    def _read_initial_state(self):
        """Read initial chart state at replay start."""
        quote = self.bridge.get_quote()
        if quote.success:
            self.log(f"Initial price: {quote.data.get('close', 'N/A')}")
            self.trader.last_price = quote.data.get("close", 0) or quote.data.get("last", 0)

        # Reset signal aggregator
        self.signal_agg.reset()

    def run(self):
        """
        Main replay loop.

        Step mode: advance one bar, read signals, check stops, repeat.
        Autoplay mode: start autoplay, poll signals on interval.
        """
        self.running = True
        self.start_time = time.time()
        self.bar_count = 0

        self.log(f"Starting replay loop (mode={'step' if self.config.step_mode else 'autoplay'})")

        if not self.config.step_mode:
            # Start autoplay
            result = self.bridge.replay_autoplay(speed=self.config.replay_speed_ms)
            if not result.success:
                self.log(f"Failed to start autoplay: {result.error}", "ERROR")
                self.running = False
                return

        try:
            while self.running:
                if self.config.step_mode:
                    self._step_loop_iteration()
                else:
                    self._autoplay_loop_iteration()

                self.bar_count += 1

                # Check bar limit
                if self.config.bars_to_run > 0 and self.bar_count >= self.config.bars_to_run:
                    self.log(f"Reached bar limit ({self.config.bars_to_run})")
                    break

                # Brief status every 100 bars
                if self.bar_count % 100 == 0:
                    self._print_status()

        except KeyboardInterrupt:
            self.log("Interrupted by user")
        except Exception as e:
            self.log(f"Error in replay loop: {e}", "ERROR")
            self.errors.append(str(e))
        finally:
            self.running = False

    def _step_loop_iteration(self):
        """One iteration of step mode: advance bar, read, trade."""
        # Step forward one bar
        result = self.bridge.replay_step()
        if not result.success:
            # Replay may have ended
            status = self.bridge.replay_status()
            if status.success and not status.data.get("is_replay_started"):
                self.log("Replay ended (no more bars)")
                self.running = False
                return
            self.errors.append(f"Step failed: {result.error}")
            time.sleep(0.5)
            return

        # Small delay for chart to update
        time.sleep(0.1)

        # Read current bar data
        self._read_and_process_bar()

    def _autoplay_loop_iteration(self):
        """One iteration of autoplay mode: poll signals."""
        # In autoplay, bars advance automatically. We poll for changes.
        time.sleep(0.3)  # Poll interval

        # Check if replay is still running
        status = self.bridge.replay_status()
        if status.success and not status.data.get("is_replay_started"):
            self.log("Replay ended")
            self.running = False
            return

        self._read_and_process_bar()

    def _read_and_process_bar(self):
        """Read current chart state, detect signals, manage trades."""
        # Get current bar data
        quote = self.bridge.get_quote()
        if not quote.success:
            return

        price = quote.data.get("close", 0) or quote.data.get("last", 0)
        high = quote.data.get("high", price)
        low = quote.data.get("low", price)
        bar_time = str(quote.data.get("time", ""))

        if price <= 0:
            return

        # Process bar through paper trader (checks stops/trails)
        stopped_trade = self.trader.on_bar(high, low, price, bar_time)
        if stopped_trade:
            self._on_trade_closed(stopped_trade)

        # Read FLOOP Pro signals
        signal = self._read_floop_signal()
        if signal and signal.is_valid:
            if self.config.log_signals:
                self.log(f"Signal: {signal.side.value} @ {price} "
                         f"(strength={signal.signal_strength}, atr={signal.atr})")

            # Feed signal to paper trader
            closed_trade = self.trader.on_signal(signal, current_price=price, bar_time=bar_time)
            if closed_trade:
                self._on_trade_closed(closed_trade)

            # Log new position if opened
            if not self.trader.is_flat:
                self.log(f"Position: {self.trader.position.side.value} "
                         f"@ {self.trader.position.entry_price} "
                         f"(stop={self.trader.position.stop_price:.2f})")

    def _read_floop_signal(self):
        """Read FLOOP Pro indicator output and detect new signals."""
        # Try labels first (most common signal source)
        labels = self.bridge.get_pine_labels(study_filter=self.config.floop_indicator_name)
        if labels.success:
            signal = self.signal_agg.check_new_signal(labels.data)
            if signal:
                # Enrich with table data if available
                tables = self.bridge.get_pine_tables(study_filter=self.config.floop_indicator_name)
                if tables.success:
                    table_info = parse_tables(tables.data, self.config.floop_indicator_name)
                    if signal.atr == 0 and "atr_value" in table_info:
                        signal.atr = table_info["atr_value"]
                    if signal.signal_strength == 0 and "signal_strength_value" in table_info:
                        signal.signal_strength = table_info["signal_strength_value"]
                return signal

        # Fallback: check study values for signal plots
        values = self.bridge.get_study_values()
        if values.success:
            study_vals = parse_study_values(values.data, self.config.floop_indicator_name)
            # Look for signal_strength and direction plots
            if "Signal Strength" in study_vals or "signal_strength" in study_vals:
                # This is ongoing indicator data, not a discrete signal
                # Only useful for enriching existing signals
                pass

        return None

    def _on_trade_closed(self, trade: Trade):
        """Handle a completed trade."""
        emoji = "W" if trade.pnl_dollars > 0 else "L"
        self.log(
            f"[{emoji}] Trade #{trade.trade_id}: {trade.side} "
            f"{trade.entry_price} -> {trade.exit_price} | "
            f"P&L: ${trade.pnl_dollars:+.2f} ({trade.pnl_ticks:+.1f} ticks) | "
            f"Reason: {trade.exit_reason} | Bars: {trade.bars_held}"
        )

        if self.config.screenshot_on_trade:
            self._take_trade_screenshot(trade)

        # Check daily limit
        if abs(self.trader.daily_pnl) >= self.config.max_daily_loss:
            self.log(f"Daily loss limit reached: ${self.trader.daily_pnl:.2f}", "WARN")

    def _take_trade_screenshot(self, trade: Trade):
        """Capture chart screenshot on trade."""
        try:
            result = self.bridge.screenshot(region="chart")
            if result.success and "path" in result.data:
                output_dir = Path(self.config.output_dir) / "screenshots"
                output_dir.mkdir(parents=True, exist_ok=True)
                # The MCP tool returns base64 or saves to a path
                self.log(f"Screenshot saved for trade #{trade.trade_id}")
        except Exception:
            pass  # Non-critical

    def _print_status(self):
        """Print periodic status update."""
        elapsed = time.time() - self.start_time
        stats = self.trader.stats
        pos_str = f"{self.trader.position.side.value}" if not self.trader.is_flat else "FLAT"

        self.log(
            f"Bar {self.bar_count} | "
            f"Price: {self.trader.last_price} | "
            f"Position: {pos_str} | "
            f"Trades: {stats['total_trades']} | "
            f"P&L: ${stats['total_pnl']:+.2f} | "
            f"Win%: {stats['win_rate']}% | "
            f"Elapsed: {elapsed:.0f}s"
        )

    def stop(self):
        """Stop replay and generate report."""
        self.running = False

        # Flatten any open position
        if not self.trader.is_flat:
            self.log("Flattening open position...")
            trade = self.trader.flatten()
            if trade:
                self._on_trade_closed(trade)

        # Stop replay mode
        self.log("Stopping replay...")
        self.bridge.replay_stop()

        # Generate report
        elapsed = time.time() - self.start_time if self.start_time else 0
        self.log("Generating report...")
        self.report.generate(
            trades=self.trader.trades,
            stats=self.trader.stats,
            config=self.config,
            bar_count=self.bar_count,
            elapsed_seconds=elapsed,
            errors=self.errors,
        )

        # Print summary
        self._print_final_summary()

        # Close log file
        if self._log_file:
            self._log_file.close()
            self._log_file = None

    def _print_final_summary(self):
        """Print final results summary."""
        stats = self.trader.stats
        elapsed = time.time() - self.start_time if self.start_time else 0

        self.log("=" * 60)
        self.log("REPLAY TEST COMPLETE")
        self.log("=" * 60)
        self.log(f"Symbol: {self.config.symbol} | TF: {self.config.timeframe}")
        self.log(f"Bars processed: {self.bar_count}")
        self.log(f"Duration: {elapsed:.1f}s ({elapsed/60:.1f}min)")
        self.log(f"")
        self.log(f"Total Trades: {stats['total_trades']}")
        self.log(f"Wins: {stats.get('wins', 0)} | Losses: {stats.get('losses', 0)}")
        self.log(f"Win Rate: {stats['win_rate']}%")
        self.log(f"Total P&L: ${stats['total_pnl']:+.2f}")
        if stats['total_trades'] > 0:
            self.log(f"Avg Win: ${stats['avg_win']:+.2f} | Avg Loss: ${stats['avg_loss']:+.2f}")
            self.log(f"Profit Factor: {stats.get('profit_factor', 0)}")
            self.log(f"Max Drawdown: ${stats.get('max_drawdown', 0):.2f}")
            self.log(f"Best Trade: ${stats.get('best_trade', 0):+.2f}")
            self.log(f"Worst Trade: ${stats.get('worst_trade', 0):+.2f}")
            self.log(f"Avg Bars Held: {stats.get('avg_bars_held', 0)}")
            self.log(f"Longs: {stats.get('longs', 0)} | Shorts: {stats.get('shorts', 0)}")
        self.log("=" * 60)


def run_replay_test(config_path: str = "", **overrides):
    """
    Convenience function to run a complete replay test.

    Usage:
        from floopbot.replay_runner import run_replay_test
        run_replay_test(symbol="MNQ1!", timeframe="5", bars_to_run=500)
    """
    config = TradingConfig.load(config_path) if config_path else TradingConfig()
    for k, v in overrides.items():
        if hasattr(config, k):
            setattr(config, k, v)

    runner = ReplayRunner(config)

    if not runner.setup():
        print("Setup failed. Is TradingView running with --remote-debugging-port=9222?")
        return None

    if not runner.start_replay():
        print("Failed to start replay mode.")
        return None

    try:
        runner.run()
    finally:
        runner.stop()

    return runner.trader.stats
