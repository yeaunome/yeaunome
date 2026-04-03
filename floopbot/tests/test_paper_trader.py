"""Tests for the paper trading engine."""

import unittest
from floopbot.config import TradingConfig
from floopbot.paper_trader import PaperTrader, PositionSide
from floopbot.signal_parser import FloopSignal, SignalSide


class TestPaperTrader(unittest.TestCase):

    def setUp(self):
        self.config = TradingConfig(
            symbol="MNQ1!",
            tick_size=0.25,
            tick_value=0.50,
            contracts=1,
            atr_stop_multiplier=1.5,
            trail_distance_atr=1.0,
            min_signal_strength=8,
            max_daily_loss=1200.0,
        )
        self.trader = PaperTrader(self.config)

    def _make_signal(self, side, price=24000.0, atr=10.0, strength=10):
        return FloopSignal(
            side=side, price=price, atr=atr,
            signal_strength=strength, source="test",
        )

    def test_initial_state(self):
        self.assertTrue(self.trader.is_flat)
        self.assertEqual(len(self.trader.trades), 0)

    def test_long_entry(self):
        sig = self._make_signal(SignalSide.LONG, price=24000)
        self.trader.on_signal(sig, current_price=24000, bar_time="2026-01-01")
        self.assertTrue(self.trader.is_long)
        self.assertEqual(self.trader.position.entry_price, 24000)
        # Stop should be 1.5 ATR below entry
        self.assertAlmostEqual(self.trader.position.stop_price, 24000 - 15)

    def test_short_entry(self):
        sig = self._make_signal(SignalSide.SHORT, price=24000)
        self.trader.on_signal(sig, current_price=24000, bar_time="2026-01-01")
        self.assertTrue(self.trader.is_short)
        self.assertAlmostEqual(self.trader.position.stop_price, 24000 + 15)

    def test_signal_strength_filter(self):
        sig = self._make_signal(SignalSide.LONG, strength=5)  # below min of 8
        self.trader.on_signal(sig, current_price=24000)
        self.assertTrue(self.trader.is_flat)  # should not enter

    def test_exit_signal(self):
        # Enter long
        entry = self._make_signal(SignalSide.LONG, price=24000)
        self.trader.on_signal(entry, current_price=24000, bar_time="2026-01-01")
        self.assertTrue(self.trader.is_long)

        # Exit
        exit_sig = self._make_signal(SignalSide.EXIT)
        trade = self.trader.on_signal(exit_sig, current_price=24010, bar_time="2026-01-01")
        self.assertIsNotNone(trade)
        self.assertTrue(self.trader.is_flat)
        self.assertGreater(trade.pnl_dollars, 0)

    def test_reversal(self):
        # Enter long
        entry = self._make_signal(SignalSide.LONG, price=24000)
        self.trader.on_signal(entry, current_price=24000, bar_time="2026-01-01")

        # Reverse to short
        reverse = self._make_signal(SignalSide.SHORT, price=24010)
        trade = self.trader.on_signal(reverse, current_price=24010, bar_time="2026-01-01")
        self.assertIsNotNone(trade)  # long was closed
        self.assertTrue(self.trader.is_short)  # now short
        self.assertGreater(trade.pnl_dollars, 0)  # long was profitable

    def test_stop_loss(self):
        # Enter long at 24000 with ATR=10, stop=24000-15=23985
        entry = self._make_signal(SignalSide.LONG, price=24000, atr=10)
        self.trader.on_signal(entry, current_price=24000, bar_time="2026-01-01")

        # Bar that hits stop
        trade = self.trader.on_bar(high=24005, low=23980, close=23982, bar_time="2026-01-01")
        self.assertIsNotNone(trade)
        self.assertEqual(trade.exit_reason, "stop_loss")
        self.assertTrue(self.trader.is_flat)

    def test_pnl_calculation(self):
        # MNQ: tick_size=0.25, tick_value=0.50, so 1 point = $2
        entry = self._make_signal(SignalSide.LONG, price=24000, atr=10)
        self.trader.on_signal(entry, current_price=24000, bar_time="2026-01-01")

        exit_sig = self._make_signal(SignalSide.EXIT)
        trade = self.trader.on_signal(exit_sig, current_price=24005, bar_time="2026-01-01")

        # 5 points * $2/point = $10
        self.assertAlmostEqual(trade.pnl_dollars, 10.0)
        # 5 points / 0.25 tick_size = 20 ticks
        self.assertAlmostEqual(trade.pnl_ticks, 20.0)

    def test_daily_loss_limit(self):
        # Enter and take a big loss
        entry = self._make_signal(SignalSide.LONG, price=24000, atr=10)
        self.trader.on_signal(entry, current_price=24000, bar_time="2026-01-01")
        # Force close at a loss that exceeds daily limit
        self.trader.daily_pnl = -1190  # close to limit
        exit_sig = self._make_signal(SignalSide.EXIT)
        self.trader.on_signal(exit_sig, current_price=23990, bar_time="2026-01-01")

        # Now try to enter again - should be blocked
        entry2 = self._make_signal(SignalSide.LONG, price=23990)
        self.trader.on_signal(entry2, current_price=23990, bar_time="2026-01-01")
        self.assertTrue(self.trader.is_flat)

    def test_stats(self):
        # Two winning trades
        for price in [24000, 24020]:
            entry = self._make_signal(SignalSide.LONG, price=price, atr=10)
            self.trader.on_signal(entry, current_price=price, bar_time="2026-01-01")
            exit_sig = self._make_signal(SignalSide.EXIT)
            self.trader.on_signal(exit_sig, current_price=price + 5, bar_time="2026-01-01")

        stats = self.trader.stats
        self.assertEqual(stats["total_trades"], 2)
        self.assertEqual(stats["wins"], 2)
        self.assertEqual(stats["win_rate"], 100.0)
        self.assertGreater(stats["total_pnl"], 0)

    def test_flatten(self):
        entry = self._make_signal(SignalSide.LONG, price=24000)
        self.trader.on_signal(entry, current_price=24000, bar_time="2026-01-01")
        trade = self.trader.flatten(price=24005)
        self.assertIsNotNone(trade)
        self.assertTrue(self.trader.is_flat)
        self.assertEqual(trade.exit_reason, "manual_flatten")


class TestSignalParser(unittest.TestCase):

    def test_classify_long(self):
        from floopbot.signal_parser import _classify_label_text
        self.assertEqual(_classify_label_text("FLOOP LONG"), SignalSide.LONG)
        self.assertEqual(_classify_label_text("floop long signal"), SignalSide.LONG)

    def test_classify_short(self):
        from floopbot.signal_parser import _classify_label_text
        self.assertEqual(_classify_label_text("FLOOP SHORT"), SignalSide.SHORT)

    def test_classify_exit(self):
        from floopbot.signal_parser import _classify_label_text
        self.assertEqual(_classify_label_text("EXIT"), SignalSide.EXIT)
        self.assertEqual(_classify_label_text("FLOOP EXIT"), SignalSide.EXIT)

    def test_extract_atr(self):
        from floopbot.signal_parser import _extract_atr
        self.assertAlmostEqual(_extract_atr("ATR: 12.5"), 12.5)
        self.assertAlmostEqual(_extract_atr("atr:8"), 8.0)

    def test_extract_strength(self):
        from floopbot.signal_parser import _extract_strength
        self.assertEqual(_extract_strength("Strength: 10/14"), 10)
        self.assertEqual(_extract_strength("signal: 8"), 8)

    def test_parse_labels(self):
        from floopbot.signal_parser import parse_labels
        data = {
            "studies": [{
                "name": "FLOOP Pro",
                "labels": [
                    {"text": "LONG", "price": 24000},
                    {"text": "SHORT", "price": 24050},
                    {"text": "PIVOT  24139.17", "price": 24139.17},
                ],
            }],
        }
        signals = parse_labels(data, "FLOOP")
        self.assertEqual(len(signals), 2)  # PIVOT should be ignored
        self.assertEqual(signals[0].side, SignalSide.LONG)
        self.assertEqual(signals[1].side, SignalSide.SHORT)

    def test_parse_labels_exact_match(self):
        from floopbot.signal_parser import _classify_label_text
        self.assertEqual(_classify_label_text("LONG"), SignalSide.LONG)
        self.assertEqual(_classify_label_text("SHORT"), SignalSide.SHORT)
        self.assertEqual(_classify_label_text("EXIT"), SignalSide.EXIT)
        # These should NOT match as signals
        self.assertEqual(_classify_label_text("PIVOT  24139.17"), SignalSide.NONE)
        self.assertEqual(_classify_label_text("R1  24398.08"), SignalSide.NONE)
        self.assertEqual(_classify_label_text("S1  23929.33"), SignalSide.NONE)


if __name__ == "__main__":
    unittest.main()
