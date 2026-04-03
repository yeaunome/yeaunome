"""
Paper trading engine for Floopbot replay testing.

Simulates the Floopbot trade execution logic:
- Entry on FLOOP Pro signals (filtered by signal strength)
- ATR-based initial stop loss
- Adaptive trailing stop
- Position tracking and P&L calculation
- Daily loss limit enforcement
"""

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from .config import TradingConfig
from .signal_parser import FloopSignal, SignalSide


class PositionSide(Enum):
    FLAT = "FLAT"
    LONG = "LONG"
    SHORT = "SHORT"


@dataclass
class Trade:
    """A completed trade with entry/exit details."""
    trade_id: int = 0
    side: str = ""  # "LONG" or "SHORT"
    entry_price: float = 0.0
    exit_price: float = 0.0
    entry_time: str = ""
    exit_time: str = ""
    contracts: int = 1
    pnl_ticks: float = 0.0
    pnl_dollars: float = 0.0
    exit_reason: str = ""  # "signal", "stop", "trail", "daily_limit", "manual"
    atr_at_entry: float = 0.0
    signal_strength: int = 0
    bars_held: int = 0
    max_favorable: float = 0.0  # max favorable excursion in ticks
    max_adverse: float = 0.0  # max adverse excursion in ticks


@dataclass
class Position:
    """Current open position state."""
    side: PositionSide = PositionSide.FLAT
    entry_price: float = 0.0
    entry_time: str = ""
    contracts: int = 0
    stop_price: float = 0.0
    trail_price: float = 0.0
    atr_at_entry: float = 0.0
    signal_strength: int = 0
    bars_held: int = 0
    max_favorable: float = 0.0
    max_adverse: float = 0.0
    high_water: float = 0.0  # best price for trailing stop


class PaperTrader:
    """
    Paper trading engine that mirrors Floopbot's execution logic.

    Usage:
        trader = PaperTrader(config)
        # On each bar:
        trader.on_bar(bar_data)
        # When signal detected:
        trader.on_signal(signal)
        # Check results:
        trader.trades, trader.stats
    """

    def __init__(self, config: TradingConfig):
        self.config = config
        self.position = Position()
        self.trades: list[Trade] = []
        self.trade_counter = 0

        # Daily tracking
        self.daily_pnl = 0.0
        self.daily_trades = 0
        self.daily_wins = 0
        self.daily_losses = 0
        self.current_date = ""

        # State
        self.armed = True
        self.last_price = 0.0
        self.last_bar_time = ""

    @property
    def is_flat(self) -> bool:
        return self.position.side == PositionSide.FLAT

    @property
    def is_long(self) -> bool:
        return self.position.side == PositionSide.LONG

    @property
    def is_short(self) -> bool:
        return self.position.side == PositionSide.SHORT

    @property
    def unrealized_pnl(self) -> float:
        """Current unrealized P&L in dollars."""
        if self.is_flat:
            return 0.0
        if self.is_long:
            return self.config.dollar_value(self.last_price - self.position.entry_price)
        return self.config.dollar_value(self.position.entry_price - self.last_price)

    @property
    def unrealized_ticks(self) -> float:
        if self.is_flat:
            return 0.0
        diff = self.last_price - self.position.entry_price
        if self.is_short:
            diff = -diff
        return diff / self.config.tick_size

    def _check_daily_limits(self) -> bool:
        """Returns True if we can still trade today."""
        if abs(self.daily_pnl) >= self.config.max_daily_loss:
            return False
        if self.daily_trades >= self.config.max_daily_trades:
            return False
        return True

    def _reset_daily(self, date_str: str):
        """Reset daily counters on new trading day."""
        if date_str != self.current_date:
            self.current_date = date_str
            self.daily_pnl = 0.0
            self.daily_trades = 0
            self.daily_wins = 0
            self.daily_losses = 0

    def on_signal(self, signal: FloopSignal, current_price: float = 0.0, bar_time: str = "") -> Optional[Trade]:
        """
        Process a FLOOP signal. Returns a completed Trade if a position was closed.

        Logic mirrors Floopbot webhook handler:
        1. Check signal strength filter
        2. If entry signal and flat -> open position
        3. If entry signal opposite direction -> reverse (close + open)
        4. If exit signal -> close position
        """
        if not signal.is_valid:
            return None

        price = current_price or signal.price or self.last_price
        if price <= 0:
            return None

        # Filter by signal strength
        if signal.is_entry and signal.signal_strength > 0:
            if signal.signal_strength < self.config.min_signal_strength:
                return None

        # Check daily limits
        if not self._check_daily_limits():
            return None

        closed_trade = None

        if signal.is_exit:
            if not self.is_flat:
                closed_trade = self._close_position(price, bar_time, "signal_exit")
            return closed_trade

        if signal.side == SignalSide.LONG:
            if self.is_short:
                # Reverse: close short, open long
                closed_trade = self._close_position(price, bar_time, "signal_reverse")
            if self.is_flat:
                self._open_position(PositionSide.LONG, price, bar_time, signal)

        elif signal.side == SignalSide.SHORT:
            if self.is_long:
                closed_trade = self._close_position(price, bar_time, "signal_reverse")
            if self.is_flat:
                self._open_position(PositionSide.SHORT, price, bar_time, signal)

        return closed_trade

    def on_bar(self, high: float, low: float, close: float, bar_time: str = "") -> Optional[Trade]:
        """
        Process a new price bar. Checks stops and trailing stops.
        Returns a Trade if the position was stopped out.
        """
        self.last_price = close
        self.last_bar_time = bar_time

        # Reset daily counters on date change
        if bar_time:
            date_part = bar_time[:10] if len(bar_time) >= 10 else bar_time
            self._reset_daily(date_part)

        if self.is_flat:
            return None

        self.position.bars_held += 1

        # Track excursions
        if self.is_long:
            favorable = (high - self.position.entry_price) / self.config.tick_size
            adverse = (self.position.entry_price - low) / self.config.tick_size
        else:
            favorable = (self.position.entry_price - low) / self.config.tick_size
            adverse = (high - self.position.entry_price) / self.config.tick_size

        self.position.max_favorable = max(self.position.max_favorable, favorable)
        self.position.max_adverse = max(self.position.max_adverse, adverse)

        # Update high water mark for trailing stop
        if self.is_long:
            self.position.high_water = max(self.position.high_water, high)
        else:
            if self.position.high_water == 0:
                self.position.high_water = low
            else:
                self.position.high_water = min(self.position.high_water, low)

        # Check hard stop
        if self._check_stop(high, low):
            return self._close_position(self.position.stop_price, bar_time, "stop_loss")

        # Update trailing stop
        self._update_trail(high, low)

        # Check trail stop
        if self._check_trail(high, low):
            return self._close_position(self.position.trail_price, bar_time, "trailing_stop")

        # Check daily loss limit with unrealized
        total_daily = self.daily_pnl + self.unrealized_pnl
        if total_daily <= -self.config.max_daily_loss:
            return self._close_position(close, bar_time, "daily_limit")

        return None

    def _open_position(self, side: PositionSide, price: float, bar_time: str, signal: FloopSignal):
        """Open a new position."""
        atr = signal.atr if signal.atr > 0 else 0.0
        stop_distance = atr * self.config.atr_stop_multiplier if atr > 0 else 0.0

        if side == PositionSide.LONG:
            stop = price - stop_distance if stop_distance > 0 else 0.0
        else:
            stop = price + stop_distance if stop_distance > 0 else 0.0

        self.position = Position(
            side=side,
            entry_price=price,
            entry_time=bar_time,
            contracts=self.config.contracts,
            stop_price=stop,
            trail_price=0.0,  # trail activates after some favorable movement
            atr_at_entry=atr,
            signal_strength=signal.signal_strength,
            high_water=price,
        )

    def _close_position(self, price: float, bar_time: str, reason: str) -> Trade:
        """Close current position and record the trade."""
        self.trade_counter += 1

        if self.position.side == PositionSide.LONG:
            pnl_points = price - self.position.entry_price
        else:
            pnl_points = self.position.entry_price - price

        pnl_ticks = pnl_points / self.config.tick_size
        pnl_dollars = self.config.dollar_value(pnl_points)

        trade = Trade(
            trade_id=self.trade_counter,
            side=self.position.side.value,
            entry_price=self.position.entry_price,
            exit_price=price,
            entry_time=self.position.entry_time,
            exit_time=bar_time,
            contracts=self.position.contracts,
            pnl_ticks=round(pnl_ticks, 2),
            pnl_dollars=round(pnl_dollars, 2),
            exit_reason=reason,
            atr_at_entry=self.position.atr_at_entry,
            signal_strength=self.position.signal_strength,
            bars_held=self.position.bars_held,
            max_favorable=round(self.position.max_favorable, 2),
            max_adverse=round(self.position.max_adverse, 2),
        )

        self.trades.append(trade)
        self.daily_pnl += pnl_dollars
        self.daily_trades += 1
        if pnl_dollars >= 0:
            self.daily_wins += 1
        else:
            self.daily_losses += 1

        # Reset position
        self.position = Position()
        return trade

    def _check_stop(self, high: float, low: float) -> bool:
        """Check if hard stop was hit."""
        if self.position.stop_price <= 0:
            return False
        if self.is_long and low <= self.position.stop_price:
            return True
        if self.is_short and high >= self.position.stop_price:
            return True
        return False

    def _update_trail(self, high: float, low: float):
        """Update adaptive trailing stop based on ATR."""
        atr = self.position.atr_at_entry
        if atr <= 0:
            return

        trail_distance = atr * self.config.trail_distance_atr

        if self.config.trail_mode == "adaptive":
            # Adaptive: tighten trail as profit increases
            if self.is_long:
                profit_atr = (self.position.high_water - self.position.entry_price) / atr if atr > 0 else 0
            else:
                profit_atr = (self.position.entry_price - self.position.high_water) / atr if atr > 0 else 0

            if profit_atr > 2.0:
                trail_distance *= 0.75  # tighten at 2x ATR profit
            if profit_atr > 3.0:
                trail_distance *= 0.6  # tighten more at 3x ATR

        if self.is_long:
            new_trail = self.position.high_water - trail_distance
            if new_trail > self.position.trail_price:
                self.position.trail_price = new_trail
                # Trail should never be below stop
                if self.position.stop_price > 0:
                    self.position.trail_price = max(self.position.trail_price, self.position.stop_price)
        else:
            new_trail = self.position.high_water + trail_distance
            if self.position.trail_price <= 0 or new_trail < self.position.trail_price:
                self.position.trail_price = new_trail
                if self.position.stop_price > 0:
                    self.position.trail_price = min(self.position.trail_price, self.position.stop_price)

    def _check_trail(self, high: float, low: float) -> bool:
        """Check if trailing stop was hit."""
        if self.position.trail_price <= 0:
            return False
        if self.is_long and low <= self.position.trail_price:
            return True
        if self.is_short and high >= self.position.trail_price:
            return True
        return False

    def flatten(self, price: float = 0.0, bar_time: str = "") -> Optional[Trade]:
        """Force close any open position."""
        if self.is_flat:
            return None
        return self._close_position(price or self.last_price, bar_time or self.last_bar_time, "manual_flatten")

    @property
    def stats(self) -> dict:
        """Summary statistics for all trades."""
        if not self.trades:
            return {
                "total_trades": 0,
                "total_pnl": 0.0,
                "win_rate": 0.0,
            }

        wins = [t for t in self.trades if t.pnl_dollars > 0]
        losses = [t for t in self.trades if t.pnl_dollars <= 0]
        total_pnl = sum(t.pnl_dollars for t in self.trades)

        avg_win = sum(t.pnl_dollars for t in wins) / len(wins) if wins else 0
        avg_loss = sum(t.pnl_dollars for t in losses) / len(losses) if losses else 0

        return {
            "total_trades": len(self.trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(len(wins) / len(self.trades) * 100, 1) if self.trades else 0,
            "total_pnl": round(total_pnl, 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "profit_factor": round(abs(sum(t.pnl_dollars for t in wins) / sum(t.pnl_dollars for t in losses)), 2) if losses and sum(t.pnl_dollars for t in losses) != 0 else float("inf"),
            "max_drawdown": round(self._max_drawdown(), 2),
            "avg_bars_held": round(sum(t.bars_held for t in self.trades) / len(self.trades), 1),
            "avg_mfe_ticks": round(sum(t.max_favorable for t in self.trades) / len(self.trades), 1),
            "avg_mae_ticks": round(sum(t.max_adverse for t in self.trades) / len(self.trades), 1),
            "best_trade": round(max(t.pnl_dollars for t in self.trades), 2),
            "worst_trade": round(min(t.pnl_dollars for t in self.trades), 2),
            "longs": len([t for t in self.trades if t.side == "LONG"]),
            "shorts": len([t for t in self.trades if t.side == "SHORT"]),
        }

    def _max_drawdown(self) -> float:
        """Calculate maximum drawdown from equity curve."""
        if not self.trades:
            return 0.0
        equity = 0.0
        peak = 0.0
        max_dd = 0.0
        for t in self.trades:
            equity += t.pnl_dollars
            peak = max(peak, equity)
            dd = peak - equity
            max_dd = max(max_dd, dd)
        return max_dd
