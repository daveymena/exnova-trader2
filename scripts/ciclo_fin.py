# -*- coding: utf-8 -*-
"""Vencimiento real de las binarias de IQ: siempre en minuto exacto."""
from __future__ import annotations

import pandas as pd


def fin_binaria(ent: pd.Timestamp, exp: int) -> pd.Timestamp:
    m = ent.floor("min") + pd.Timedelta(minutes=1)
    primero = m if (m - ent).total_seconds() > 30 else m + pd.Timedelta(minutes=1)
    return primero + pd.Timedelta(minutes=exp - 1)
