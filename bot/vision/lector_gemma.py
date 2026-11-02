# -*- coding: utf-8 -*-
"""
Lector de graficos con un modelo de vision (Gemma en Ollama Cloud).

Dibuja las ultimas velas de 15 s con EMA 20/50/200 (como el Edge Scanner del
usuario), se las muestra al modelo y le pide una decision de opcion binaria:
CALL, PUT o NO operar, con vencimiento de 2, 3 o 5 min.

Configuracion en .env:
  OLLAMA_API_KEY       key de https://ollama.com/settings/keys
  OLLAMA_CLOUD_URL     https://ollama.com  (o http://localhost:11434 con Ollama local)
  OLLAMA_VISION_MODEL  gemma4:31b
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import threading

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
import requests  # noqa: E402

VELAS = 120          # 30 min de velas de 15 s
FIG_LOCK = threading.Lock()   # pyplot no admite dibujar desde varios hilos

PROMPT = """Eres el agente de trading de Duvier y entras como el, en opciones binarias de IQ Option.
La imagen muestra los ultimos 30 minutos en velas de 15 segundos de {activo}.
Lineas: EMA20 verde, EMA50 amarilla, EMA200 roja. La ultima vela de la derecha acaba de cerrar;
si entras, entras ahora a ese precio.

Revisa en este orden. Si una regla no se cumple, NO. Si dudas, NO.
1. Direccion: CALL solo con el precio por encima de la EMA20; PUT solo por debajo.
   El orden de las tres EMAs NO decide la direccion, solo da contexto.
2. Lugar de entrada, uno de estos setups:
   A rechazo: estructura con maximos decrecientes; el precio sube a un techo o a la EMA20, lo
     rechazan y la primera vela roja es la entrada PUT (al reves para CALL: piso rechazado).
   B retroceso: impulso y retroceso corto que toca la EMA20 sin cerrar al otro lado de la EMA50;
     entrada cuando la vela rompe el maximo de la anterior en el primer minimo creciente (CALL),
     o el minimo en el primer maximo decreciente (PUT).
   C piso de rango: rango lateral con soporte claro; CALL en el rebote en el piso.
3. Prohibido entrar (NO aunque la direccion sea correcta):
   F1 en el extremo: vender en el piso tras una caida larga o comprar en el techo tras una subida.
   F2 tras la vela de impulso: la ultima vela es un impulso grande a tu favor y lo estarias persiguiendo.
   F3 contra la estructura: una sola vela contra una estructura clara.
   Lateral estrecho sin direccion, con velas pequenas y EMAs enredadas.
4. Vencimiento: 2 minutos normalmente, 3 si el movimiento necesita algo mas de espacio; 5 casi nunca.

Responde SOLO con JSON:
{{"decision": "CALL" | "PUT" | "NO", "setup": "A" | "B" | "C" | "", "vencimiento_min": 2 | 3 | 5, "confianza": 0-100, "razon": "maximo 25 palabras"}}"""


def _cfg():
    return (os.getenv("OLLAMA_CLOUD_URL", "https://ollama.com").rstrip("/"),
            os.getenv("OLLAMA_API_KEY", ""), os.getenv("OLLAMA_VISION_MODEL", "gemma4:31b"))


def _panel(ax, df: pd.DataFrame, n: int, titulo: str) -> None:
    ema = {p: df["close"].ewm(span=p, adjust=False).mean() for p in (20, 50, 200)}
    w = df.iloc[-n:]
    ax.set_facecolor("#141922")
    for i, r in enumerate(w.itertuples()):
        col = "#2fbf86" if r.close >= r.open else "#ef5b69"
        ax.vlines(i, r.low, r.high, color=col, linewidth=0.8)
        ax.add_patch(plt.Rectangle((i - 0.3, min(r.open, r.close)), 0.6,
                                   max(abs(r.close - r.open), 1e-12), color=col))
    for p, col in ((20, "#3ccf7d"), (50, "#f2c230"), (200, "#f05a5a")):
        ax.plot(range(len(w)), ema[p].iloc[-n:].to_numpy(), color=col, linewidth=1.4)
    ax.set_xlim(-1, len(w) + 3)
    ax.tick_params(colors="#94a0b2", labelsize=7)
    ax.yaxis.tick_right()
    ax.set_xticks([0, len(w) // 2, len(w) - 1])
    ax.set_xticklabels([f"{t:%H:%M}" for t in (w.index[0], w.index[len(w) // 2], w.index[-1])])
    for s in ax.spines.values():
        s.set_color("#2b3340")
    ax.set_title(titulo, color="#e6eaf0", fontsize=9, loc="left")


def render_png(df: pd.DataFrame, activo: str = "", panoramica: bool = False) -> bytes:
    """df: velas de 15 s (open/high/low/close) con historia suficiente para la EMA200."""
    with FIG_LOCK:
        if panoramica:
            m1 = df.resample("1min").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
            fig, (a0, a1) = plt.subplots(2, 1, figsize=(9, 7), dpi=80)
            _panel(a0, m1, len(m1), f"{activo}  panoramica velas 1 min")
            _panel(a1, df, VELAS, f"{activo}  ultimos 30 min velas 15 s")
        else:
            fig, a1 = plt.subplots(figsize=(9, 4.5), dpi=90)
            _panel(a1, df, VELAS, f"{activo}  velas 15 s")
        fig.patch.set_facecolor("#141922")
        buf = io.BytesIO()
        fig.tight_layout()
        fig.savefig(buf, format="png", facecolor=fig.get_facecolor())
        plt.close(fig)
    return buf.getvalue()


def leer(df: pd.DataFrame, activo: str = "", timeout: float = 90) -> dict:
    """Devuelve {"decision", "vencimiento_min", "setup", "confianza", "razon"}; NO si la respuesta no sirve."""
    url, key, model = _cfg()
    png = render_png(df, activo)
    body = {"model": model, "stream": False, "format": "json",
            "options": {"temperature": 0},
            "messages": [{"role": "user", "content": PROMPT.format(activo=activo or "el activo"),
                          "images": [base64.b64encode(png).decode()]}]}
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    r = requests.post(f"{url}/api/chat", json=body, headers=headers, timeout=timeout)
    r.raise_for_status()
    txt = r.json()["message"]["content"]
    m = re.search(r"\{.*\}", txt, re.S)
    out = json.loads(m.group(0)) if m else {}
    d = str(out.get("decision", "NO")).upper()
    v = int(out.get("vencimiento_min", 2) or 2)
    return {"decision": d if d in ("CALL", "PUT") else "NO",
            "vencimiento_min": v if v in (2, 3, 5) else 2,
            "setup": str(out.get("setup", ""))[:2],
            "confianza": int(out.get("confianza", 0) or 0),
            "razon": str(out.get("razon", ""))[:200]}


def modelos() -> list[str]:
    url, key, _ = _cfg()
    r = requests.get(f"{url}/api/tags", headers={"Authorization": f"Bearer {key}"} if key else {}, timeout=30)
    r.raise_for_status()
    return [m["name"] for m in r.json().get("models", [])]
