"""
Report generator for Floopbot replay test results.

Outputs:
1. JSON report with all trades and statistics
2. Human-readable text summary
3. CSV trade log for spreadsheet analysis
4. Equity curve data
"""

import csv
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from .config import TradingConfig
from .paper_trader import Trade


class ReportGenerator:
    """Generate comprehensive reports from replay test results."""

    def __init__(self, config: TradingConfig):
        self.config = config
        self.output_dir = Path(config.output_dir)
        self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    def generate(
        self,
        trades: list[Trade],
        stats: dict,
        config: TradingConfig,
        bar_count: int = 0,
        elapsed_seconds: float = 0,
        errors: list[str] = None,
    ):
        """Generate all report files."""
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self._write_json_report(trades, stats, config, bar_count, elapsed_seconds, errors)
        self._write_csv_trades(trades)
        self._write_equity_csv(trades)
        self._write_text_summary(trades, stats, config, bar_count, elapsed_seconds)

    def _write_json_report(
        self, trades, stats, config, bar_count, elapsed_seconds, errors
    ):
        """Full JSON report with all data."""
        report = {
            "meta": {
                "timestamp": self.timestamp,
                "symbol": config.symbol,
                "timeframe": config.timeframe,
                "bars_processed": bar_count,
                "elapsed_seconds": round(elapsed_seconds, 1),
                "version": "1.0.0",
            },
            "config": {
                "min_signal_strength": config.min_signal_strength,
                "atr_stop_multiplier": config.atr_stop_multiplier,
                "trail_distance_atr": config.trail_distance_atr,
                "trail_mode": config.trail_mode,
                "contracts": config.contracts,
                "max_daily_loss": config.max_daily_loss,
                "tick_size": config.tick_size,
                "tick_value": config.tick_value,
            },
            "stats": stats,
            "equity_curve": self._build_equity_curve(trades),
            "trades": [asdict(t) for t in trades],
            "by_exit_reason": self._group_by_exit_reason(trades),
            "by_side": self._group_by_side(trades),
            "daily_breakdown": self._daily_breakdown(trades),
            "errors": errors or [],
        }

        path = self.output_dir / f"report_{self.timestamp}.json"
        path.write_text(json.dumps(report, indent=2))

    def _write_csv_trades(self, trades: list[Trade]):
        """CSV file with one row per trade."""
        if not trades:
            return

        path = self.output_dir / f"trades_{self.timestamp}.csv"
        fields = [
            "trade_id", "side", "entry_price", "exit_price",
            "entry_time", "exit_time", "contracts",
            "pnl_ticks", "pnl_dollars", "exit_reason",
            "atr_at_entry", "signal_strength", "bars_held",
            "max_favorable", "max_adverse",
        ]

        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            for t in trades:
                writer.writerow(asdict(t))

    def _write_equity_csv(self, trades: list[Trade]):
        """CSV of cumulative equity curve."""
        if not trades:
            return

        path = self.output_dir / f"equity_{self.timestamp}.csv"
        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["trade_num", "cumulative_pnl", "drawdown", "exit_time"])
            equity = 0.0
            peak = 0.0
            for t in trades:
                equity += t.pnl_dollars
                peak = max(peak, equity)
                dd = peak - equity
                writer.writerow([t.trade_id, round(equity, 2), round(dd, 2), t.exit_time])

    def _write_text_summary(self, trades, stats, config, bar_count, elapsed_seconds):
        """Human-readable text report."""
        path = self.output_dir / f"summary_{self.timestamp}.txt"

        lines = [
            "=" * 60,
            f"FLOOPBOT REPLAY TEST REPORT",
            f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "=" * 60,
            "",
            "CONFIGURATION",
            "-" * 40,
            f"Symbol:              {config.symbol}",
            f"Timeframe:           {config.timeframe}",
            f"Contracts:           {config.contracts}",
            f"ATR Stop Multiplier: {config.atr_stop_multiplier}x",
            f"Trail Distance:      {config.trail_distance_atr}x ATR ({config.trail_mode})",
            f"Min Signal Strength: {config.min_signal_strength}/{config.max_signal_strength}",
            f"Max Daily Loss:      ${config.max_daily_loss}",
            f"Tick Size/Value:     {config.tick_size} / ${config.tick_value}",
            "",
            "RESULTS",
            "-" * 40,
            f"Bars Processed:  {bar_count}",
            f"Test Duration:   {elapsed_seconds:.1f}s ({elapsed_seconds/60:.1f}min)",
            f"Total Trades:    {stats['total_trades']}",
            f"Win Rate:        {stats['win_rate']}%",
            f"Total P&L:       ${stats['total_pnl']:+.2f}",
            "",
        ]

        if stats["total_trades"] > 0:
            lines.extend([
                "DETAILED STATS",
                "-" * 40,
                f"Wins:            {stats.get('wins', 0)}",
                f"Losses:          {stats.get('losses', 0)}",
                f"Avg Win:         ${stats.get('avg_win', 0):+.2f}",
                f"Avg Loss:        ${stats.get('avg_loss', 0):+.2f}",
                f"Profit Factor:   {stats.get('profit_factor', 0)}",
                f"Max Drawdown:    ${stats.get('max_drawdown', 0):.2f}",
                f"Best Trade:      ${stats.get('best_trade', 0):+.2f}",
                f"Worst Trade:     ${stats.get('worst_trade', 0):+.2f}",
                f"Avg Bars Held:   {stats.get('avg_bars_held', 0)}",
                f"Avg MFE (ticks): {stats.get('avg_mfe_ticks', 0)}",
                f"Avg MAE (ticks): {stats.get('avg_mae_ticks', 0)}",
                f"Longs:           {stats.get('longs', 0)}",
                f"Shorts:          {stats.get('shorts', 0)}",
                "",
                "EXIT REASONS",
                "-" * 40,
            ])

            by_reason = self._group_by_exit_reason(trades)
            for reason, data in by_reason.items():
                lines.append(f"  {reason}: {data['count']} trades, ${data['total_pnl']:+.2f}")

            lines.extend([
                "",
                "TRADE LOG",
                "-" * 40,
                f"{'#':>4} {'Side':>5} {'Entry':>10} {'Exit':>10} {'P&L':>10} {'Ticks':>7} {'Reason':>15} {'Bars':>5}",
            ])

            for t in trades:
                lines.append(
                    f"{t.trade_id:>4} {t.side:>5} {t.entry_price:>10.2f} {t.exit_price:>10.2f} "
                    f"${t.pnl_dollars:>+9.2f} {t.pnl_ticks:>+6.1f} {t.exit_reason:>15} {t.bars_held:>5}"
                )

        lines.append("")
        lines.append("=" * 60)
        path.write_text("\n".join(lines))

    def _build_equity_curve(self, trades: list[Trade]) -> list[dict]:
        """Build equity curve data points."""
        curve = []
        equity = 0.0
        peak = 0.0
        for t in trades:
            equity += t.pnl_dollars
            peak = max(peak, equity)
            curve.append({
                "trade": t.trade_id,
                "equity": round(equity, 2),
                "drawdown": round(peak - equity, 2),
                "time": t.exit_time,
            })
        return curve

    def _group_by_exit_reason(self, trades: list[Trade]) -> dict:
        """Group trade stats by exit reason."""
        groups = {}
        for t in trades:
            reason = t.exit_reason
            if reason not in groups:
                groups[reason] = {"count": 0, "total_pnl": 0.0, "wins": 0, "losses": 0}
            groups[reason]["count"] += 1
            groups[reason]["total_pnl"] = round(groups[reason]["total_pnl"] + t.pnl_dollars, 2)
            if t.pnl_dollars > 0:
                groups[reason]["wins"] += 1
            else:
                groups[reason]["losses"] += 1
        return groups

    def _group_by_side(self, trades: list[Trade]) -> dict:
        """Group trade stats by side (LONG/SHORT)."""
        groups = {}
        for t in trades:
            side = t.side
            if side not in groups:
                groups[side] = {"count": 0, "total_pnl": 0.0, "wins": 0, "losses": 0, "avg_pnl": 0.0}
            groups[side]["count"] += 1
            groups[side]["total_pnl"] = round(groups[side]["total_pnl"] + t.pnl_dollars, 2)
            if t.pnl_dollars > 0:
                groups[side]["wins"] += 1
            else:
                groups[side]["losses"] += 1
            groups[side]["avg_pnl"] = round(groups[side]["total_pnl"] / groups[side]["count"], 2)
        return groups

    def _daily_breakdown(self, trades: list[Trade]) -> dict:
        """Group trades by day."""
        days = {}
        for t in trades:
            day = t.entry_time[:10] if len(t.entry_time) >= 10 else t.entry_time
            if not day:
                day = "unknown"
            if day not in days:
                days[day] = {"trades": 0, "pnl": 0.0, "wins": 0, "losses": 0}
            days[day]["trades"] += 1
            days[day]["pnl"] = round(days[day]["pnl"] + t.pnl_dollars, 2)
            if t.pnl_dollars > 0:
                days[day]["wins"] += 1
            else:
                days[day]["losses"] += 1
        return days
