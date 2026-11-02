"""Shared trust policy for market candle feeds.

Default accepted sources are the broker adapters maintained in this project.
A new historical provider must be explicitly allow-listed through
TRUSTED_CANDLE_SOURCES instead of being trusted merely because it is not named
"mock".
"""
import os


DEFAULT_TRUSTED_CANDLE_SOURCES = frozenset({"exnova", "iqoption"})


def trusted_candle_sources() -> set[str]:
    raw = os.getenv("TRUSTED_CANDLE_SOURCES", "exnova,iqoption")
    values = {
        item.strip().lower()
        for item in raw.split(",")
        if item.strip()
    }
    return values or set(DEFAULT_TRUSTED_CANDLE_SOURCES)


def is_trusted_candle_source(source) -> bool:
    value = str(source or "").strip().lower()
    return bool(value) and value in trusted_candle_sources()
