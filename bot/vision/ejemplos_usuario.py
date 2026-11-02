# -*- coding: utf-8 -*-
"""
Ejemplos reales del usuario para que Gemma imite sus entradas.

Salen de la primera mitad cronologica de sus operaciones (mas momentos del mismo
periodo en los que no entro), la misma seleccion medida en scripts/replica_gemma.py:
la segunda mitad queda como examen no visto.
"""
from __future__ import annotations

import base64
import json
import os
import random
import re
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from bot.vision.lector_gemma import _cfg, render_png

ROOT = Path(__file__).resolve().parent.parent.parent
H = ROOT / "bot" / "data" / "history"
BARS = 400
PANORAMA = 800       # 200 min de velas de 15 s: alcanza para el panel de 1 min
MARGEN = 600         # los controles quedan a mas de 10 min de cualquier entrada suya

PROMPT = """Eres el agente de Duvier y debes imitar sus entradas de opciones binarias.
Cada imagen tiene dos paneles. Arriba, panoramica en velas de 1 min: ubica ahi soportes, resistencias, la tendencia y si el impulso esta empezando o terminando.
Abajo, los ultimos 30 min en velas de 15 s; EMA20 verde, EMA50 amarilla, EMA200 roja; la ultima vela de la derecha es el instante de decidir.
No compres llegando a una resistencia ni vendas llegando a un soporte: entra al comienzo del movimiento.
Las primeras {n} imagenes son decisiones reales:
{lista}
La ultima imagen ({activo}) es el momento actual. {pregunta}
Responde SOLO JSON: {{"decision":"CALL"|"PUT"|"NO","confianza":0-100,"razon":"max 20 palabras"}}"""
LIBRE = "Di que haria Duvier segun esos ejemplos."
VETO = ("La direccion propuesta es {d}. Lee el grafico en este orden: 1) tendencia en la panoramica; "
        "2) soporte o resistencia mas cercano hacia donde iria {d}; 3) fase del movimiento en 15 s: inicio, medio o final. "
        "Duvier solo entra en inicio de movimiento o retroceso terminado, con camino libre. Si se cumple responde {d}; "
        "si no, responde NO. Pon en razon: tendencia, nivel y fase.")


def _load(asset: str) -> pd.DataFrame:
    df = pd.read_parquet(H / f"{asset}_15.parquet")[["open", "high", "low", "close"]].astype(float)
    return df[~df.index.duplicated()].sort_index()


def ventana(df: pd.DataFrame, ts: pd.Timestamp) -> pd.DataFrame:
    return df[df.index + pd.Timedelta(seconds=15) <= ts].iloc[-PANORAMA:]


def casos(mapa: dict, seed: int = 7) -> list[dict]:
    """Sus operaciones y un control por cada una, con la ventana de velas previa."""
    rnd = random.Random(seed)
    trades = json.load(open(ROOT / "reports" / "graficos_rs_data.json", encoding="utf-8"))["trades"]
    out, cache = [], {}
    for t in trades:
        a = mapa[t["asset"]]
        cache.setdefault(a, _load(a))
        out.append({"tipo": "suya", "id": t["id"], "asset": a, "ts": pd.Timestamp(t["entry_ts"], unit="s"),
                    "dir": t["dir"], "res": t["res"]})
    for i, c in enumerate(list(out)):
        df = cache[c["asset"]]
        suyas = [x["ts"] for x in out if x["tipo"] == "suya" and x["asset"] == c["asset"]]
        idx = df.index[BARS:]
        libre = np.ones(len(idx), dtype=bool)
        for s in suyas:
            libre &= np.abs((idx - s).total_seconds().to_numpy()) > MARGEN
        libres = list(idx[libre])
        if libres:
            ts = rnd.choice(libres) + pd.Timedelta(seconds=15)
            out.append({"tipo": "control", "id": f"K{i + 1:02d}", "asset": c["asset"], "ts": ts, "dir": "", "res": ""})
    for c in out:
        c["v"] = ventana(cache[c["asset"]], c["ts"])
    return [c for c in out if len(c["v"]) >= 300 and (c["ts"] - c["v"].index[-1]).total_seconds() <= 30]


def _toma(lista: list, n: int) -> list:
    return lista[::max(1, len(lista) // n)][:n]


def seleccionar(mapa: dict) -> list[tuple[str, str]]:
    """Devuelve [(png_base64, etiqueta)]: 4 CALL, 4 PUT y 6 momentos sin entrada."""
    cs = casos(mapa)
    s = sorted((c for c in cs if c["tipo"] == "suya"), key=lambda c: c["ts"])
    corte = s[len(s) // 2]["ts"]
    previas = [c for c in s if c["ts"] < corte]
    ctrl = sorted((c for c in cs if c["tipo"] == "control" and c["ts"] < corte), key=lambda c: c["ts"])
    ej = [(c, f"Duvier entro {c['dir']}") for d in ("CALL", "PUT") for c in _toma([x for x in previas if x["dir"] == d], 4)]
    ej += [(c, "Duvier NO entro") for c in _toma(ctrl, 6)]
    return [(imagen(c["v"], c["asset"]), t) for c, t in ej]


def imagen(df: pd.DataFrame, activo: str) -> str:
    return base64.b64encode(render_png(df, activo, panoramica=True)).decode()


def leer_como_usuario(df: pd.DataFrame, activo: str, ejemplos: list[tuple[str, str]], timeout: float = 30,
                      propuesta: str = "") -> dict:
    url, key, model = _cfg()
    lista = "\n".join(f"Imagen {i + 1}: {t}." for i, (_, t) in enumerate(ejemplos))
    png = imagen(df, activo)
    body = {"model": model, "stream": False, "format": "json", "options": {"temperature": 0},
            "messages": [{"role": "user", "content": PROMPT.format(
                              n=len(ejemplos), lista=lista, activo=activo,
                              pregunta=VETO.format(d=propuesta) if propuesta else LIBRE),
                          "images": [p for p, _ in ejemplos] + [png]}]}
    r = requests.post(f"{url}/api/chat", json=body, headers={"Authorization": f"Bearer {key}"}, timeout=timeout)
    r.raise_for_status()
    txt = r.json()["message"]["content"]
    m = re.search(r"\{.*\}", txt, re.S)
    out = json.loads(m.group(0)) if m else {}
    d = str(out.get("decision", "NO")).upper()
    return {"decision": d if d in ("CALL", "PUT") else "NO", "vencimiento_min": 3,
            "confianza": int(out.get("confianza", 0) or 0), "razon": str(out.get("razon", ""))[:200]}
