# -*- coding: utf-8 -*-
"""
Setup C del patron "Retroceso a favor" de Duvier (detector_rs_patron.py):
CALL en el piso de un rango ancho con EMAs 20/50/200 planas, piso tocado 2+
veces y mecha de rechazo o vela gatillo. Solo el lado CALL: en la prueba con
velas de 5 min (scripts/lab_patron_c_iq.py) el PUT en techo dio 48 %.
"""
from __future__ import annotations

import pandas as pd

from bot.backtest import detector_rs_patron as det

PARAMS = det.Params(rango_velas=20)
BARS = 300          # EMA200 + rango + margen


def _detector(df: pd.DataFrame):
    v = [dict(t=t, o=r.open, h=r.high, l=r.low, c=r.close) for t, r in zip(df.index, df.itertuples())]
    return det.Detector(v, PARAMS)


def patron_c_signals(df: pd.DataFrame) -> pd.DataFrame:
    """Columnas call/put; solo se evalua la ultima vela cerrada."""
    out = pd.DataFrame({"call": False, "put": False}, index=df.index)
    s = _detector(df).senal(len(df) - 1)
    if s and s["setup"] == "C_CALL_piso_rango":
        out.iloc[-1, 0] = True
    return out


def patron_c_features(df: pd.DataFrame) -> dict:
    """Contexto de la senal para la revision periodica (scripts/revisar_live.py)."""
    d = _detector(df)
    i = len(df) - 1
    s = d.senal(i) or {}
    a = d.atr[i]
    pend = (d.e20[i] - d.e20[i - PARAMS.pendiente_velas]) / (PARAMS.pendiente_velas * a)
    lo = min(x["l"] for x in d.v[i - PARAMS.rango_velas + 1:i + 1])
    hi = max(x["h"] for x in d.v[i - PARAMS.rango_velas + 1:i + 1])
    return {"toques": s.get("toques"), "pos": s.get("pos"),
            "rango_atr": round((hi - lo) / a, 2), "pend_e20": round(pend, 3),
            "dist_e200_atr": round((d.v[i]["c"] - d.e200[i]) / a, 2),
            "hora_utc": int(df.index[-1].hour)}
