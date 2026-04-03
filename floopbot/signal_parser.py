"""
Parse FLOOP Pro indicator signals from TradingView chart data.

The FLOOP Pro indicator outputs signals via:
1. Pine labels (text annotations like "FLOOP LONG", "FLOOP SHORT")
2. Pine tables (session stats, signal strength dashboard)
3. Study values (numeric indicator values)
4. Pine lines (horizontal price levels for S/R, stops)

This parser reads all of these and produces structured Signal objects.
"""

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class SignalSide(Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    EXIT = "EXIT"
    NONE = "NONE"


@dataclass
class FloopSignal:
    """A parsed signal from the FLOOP Pro indicator."""
    side: SignalSide = SignalSide.NONE
    price: float = 0.0
    atr: float = 0.0
    signal_strength: int = 0
    stop_price: float = 0.0
    timestamp: float = 0.0
    raw_text: str = ""
    source: str = ""  # "label", "table", "value"

    @property
    def is_entry(self) -> bool:
        return self.side in (SignalSide.LONG, SignalSide.SHORT)

    @property
    def is_exit(self) -> bool:
        return self.side == SignalSide.EXIT

    @property
    def is_valid(self) -> bool:
        return self.side != SignalSide.NONE


# ── Label patterns matching FLOOP Pro alert messages ──

# From the dashboard screenshot, alert messages look like:
# {"secret":"floopbot","action":"entry","side":"LONG","price":{{close}},
#  "atr":{{plot("ATR")}},"signal_strength":{{plot("Signal Strength")}},
#  "comment":"FLOOP LONG"}

LONG_PATTERNS = [
    re.compile(r"^LONG$", re.IGNORECASE),
    re.compile(r"FLOOP\s*LONG", re.IGNORECASE),
    re.compile(r"(?:BUY|LONG)\s*SIGNAL", re.IGNORECASE),
    re.compile(r"(?:▲|↑)\s*(?:LONG|BUY)", re.IGNORECASE),
]

SHORT_PATTERNS = [
    re.compile(r"^SHORT$", re.IGNORECASE),
    re.compile(r"FLOOP\s*SHORT", re.IGNORECASE),
    re.compile(r"(?:SELL|SHORT)\s*SIGNAL", re.IGNORECASE),
    re.compile(r"(?:▼|↓)\s*(?:SHORT|SELL)", re.IGNORECASE),
]

EXIT_PATTERNS = [
    re.compile(r"^EXIT$", re.IGNORECASE),
    re.compile(r"FLOOP\s*EXIT", re.IGNORECASE),
    re.compile(r"(?:CLOSE|FLATTEN)", re.IGNORECASE),
    re.compile(r"(?:✕|×)\s*(?:EXIT|CLOSE)", re.IGNORECASE),
]

ATR_PATTERN = re.compile(r"ATR[:\s]*([0-9]+\.?[0-9]*)", re.IGNORECASE)
STRENGTH_PATTERN = re.compile(r"(?:strength|signal|str|sig)[:\s]*([0-9]+)\s*/?\s*([0-9]+)?", re.IGNORECASE)
PRICE_PATTERN = re.compile(r"(?:price|@|entry)[:\s]*([0-9]+\.?[0-9]*)", re.IGNORECASE)


def _classify_label_text(text: str) -> SignalSide:
    """Determine signal direction from label text."""
    for pattern in LONG_PATTERNS:
        if pattern.search(text):
            return SignalSide.LONG
    for pattern in SHORT_PATTERNS:
        if pattern.search(text):
            return SignalSide.SHORT
    for pattern in EXIT_PATTERNS:
        if pattern.search(text):
            return SignalSide.EXIT
    return SignalSide.NONE


def _extract_atr(text: str) -> float:
    m = ATR_PATTERN.search(text)
    return float(m.group(1)) if m else 0.0


def _extract_strength(text: str) -> int:
    m = STRENGTH_PATTERN.search(text)
    return int(m.group(1)) if m else 0


def _extract_price_from_text(text: str) -> float:
    m = PRICE_PATTERN.search(text)
    return float(m.group(1)) if m else 0.0


def parse_labels(label_data: dict, indicator_name: str = "FLOOP") -> list[FloopSignal]:
    """
    Parse signals from pine label data.

    label_data: output from tv MCP `data_get_pine_labels`
    Returns list of FloopSignal objects, most recent first.
    """
    signals = []

    studies = label_data.get("studies", [])
    for study in studies:
        name = study.get("name", "")
        if indicator_name and indicator_name.lower() not in name.lower():
            continue

        for label in study.get("labels", []):
            text = label.get("text", "")
            price = label.get("price", 0.0) or 0.0

            side = _classify_label_text(text)
            if side == SignalSide.NONE:
                continue

            sig = FloopSignal(
                side=side,
                price=price or _extract_price_from_text(text),
                atr=_extract_atr(text),
                signal_strength=_extract_strength(text),
                raw_text=text,
                source="label",
            )
            signals.append(sig)

    return signals


def parse_tables(table_data: dict, indicator_name: str = "FLOOP") -> dict:
    """
    Parse FLOOP Pro table data for session stats and config values.

    Actual FLOOP Pro table format:
      "  QUALITY | LOW  6/14  "
      "  Vol LOW (2%ile) | ATR 0.04%  "
      "  BEARISH | HTF BULL"

    Returns dict with keys like:
    - signal_strength_value, atr_pct, bias, quality, etc.
    """
    result = {}
    studies = table_data.get("studies", [])

    for study in studies:
        name = study.get("name", "")
        if indicator_name and indicator_name.lower() not in name.lower():
            continue

        for table in study.get("tables", []):
            rows = table.get("rows", [])
            for row_text in rows:
                stripped = row_text.strip()

                # Extract signal strength from "QUALITY | LOW  6/14"
                quality_match = re.search(r"QUALITY\s*\|\s*\w+\s+(\d+)\s*/\s*(\d+)", stripped, re.IGNORECASE)
                if quality_match:
                    result["signal_strength_value"] = int(quality_match.group(1))
                    result["signal_strength_max"] = int(quality_match.group(2))
                    result["quality"] = stripped

                # Extract ATR from "ATR 0.04%" or "ATR: 12.5"
                atr_match = re.search(r"ATR\s+([0-9.]+)%?", stripped)
                if atr_match:
                    result["atr_pct"] = float(atr_match.group(1))

                # Extract bias from "BEARISH | HTF BULL"
                if re.search(r"BEARISH|BULLISH", stripped, re.IGNORECASE):
                    result["bias"] = "BEARISH" if "BEARISH" in stripped.upper() else "BULLISH"
                    result["htf_bias"] = "BULL" if "HTF BULL" in stripped.upper() else "BEAR" if "HTF BEAR" in stripped.upper() else ""

                # Parse "Key | Value" format for everything else
                if " | " in stripped:
                    parts = stripped.split(" | ")
                    if len(parts) >= 2:
                        key = parts[0].strip().lower().replace(" ", "_")
                        val = parts[1].strip()
                        result[key] = val

    return result


def parse_study_values(values_data: dict, indicator_name: str = "FLOOP") -> dict:
    """
    Parse numeric study values from the indicator data window.

    Returns dict of plot name -> value.
    """
    result = {}
    studies = values_data.get("studies", [])

    for study in studies:
        name = study.get("name", "")
        if indicator_name and indicator_name.lower() not in name.lower():
            continue

        values = study.get("values", {})
        for k, v in values.items():
            try:
                result[k] = float(v) if "." in str(v) else int(v)
            except (ValueError, TypeError):
                result[k] = v

    return result


def parse_lines(lines_data: dict, indicator_name: str = "FLOOP") -> dict:
    """
    Parse horizontal price levels from the indicator.

    Returns dict with keys like 'levels', 'stop_levels', etc.
    """
    result = {"levels": [], "all_levels": []}
    studies = lines_data.get("studies", [])

    for study in studies:
        name = study.get("name", "")
        if indicator_name and indicator_name.lower() not in name.lower():
            continue

        levels = study.get("horizontal_levels", [])
        result["all_levels"] = levels
        result["levels"] = levels

    return result


def parse_boxes(boxes_data: dict, indicator_name: str = "FLOOP") -> list[dict]:
    """
    Parse price zones (supply/demand, support/resistance) from boxes.

    Returns list of {high, low} zone dicts.
    """
    zones = []
    studies = boxes_data.get("studies", [])

    for study in studies:
        name = study.get("name", "")
        if indicator_name and indicator_name.lower() not in name.lower():
            continue

        for zone in study.get("zones", []):
            zones.append({"high": zone.get("high", 0), "low": zone.get("low", 0)})

    return zones


class SignalAggregator:
    """
    Tracks signal state across multiple bar updates.
    Detects NEW signals by comparing to previously seen signals.
    """

    def __init__(self, indicator_name: str = "FLOOP"):
        self.indicator_name = indicator_name
        self._last_label_count = 0
        self._last_signal_text = ""
        self._last_signal: Optional[FloopSignal] = None

    def check_new_signal(self, label_data: dict) -> Optional[FloopSignal]:
        """
        Compare current labels to previous state.
        Returns a FloopSignal only if there's a NEW signal we haven't seen.
        """
        signals = parse_labels(label_data, self.indicator_name)
        if not signals:
            return None

        # The most recent signal is the last one added
        latest = signals[-1]

        # Detect new signal by comparing text and count
        current_count = len(signals)
        if current_count > self._last_label_count or latest.raw_text != self._last_signal_text:
            self._last_label_count = current_count
            self._last_signal_text = latest.raw_text
            self._last_signal = latest
            return latest

        return None

    def reset(self):
        self._last_label_count = 0
        self._last_signal_text = ""
        self._last_signal = None
