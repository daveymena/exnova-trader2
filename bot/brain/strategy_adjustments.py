"""Memoria de ajustes de la estrategia (escrita por el bucle de mejora IA).

El bot live lee este JSON antes de operar para aplicar la calibracion
que la IA produce cada N trades. Esto convierte la estrategia en "nuestra":
se refina ciclo a ciclo.

Schema (bot/brain/strategy_adjustments.json):
{
  "version": 1,
  "updated": <epoch>,
  "cycle": <int>,
  "min_confidence": 0.70,                  # override de MIN_CONFIDENCE (o null)
  "expiry_by_asset": {"EURUSD-OTC": 3},   # minutos por activo (override)
  "assets_pause": ["USDJPY-OTC"],          # activos pausados
  "lessons": [{"ts":..., "text": "..."}],  # lecciones acumuladas (alimentan el prompt)
  "history": [{...}]                        # ultimos ciclos (auditable)
}
"""
import json
import os
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

ADJUSTMENTS_PATH = Path(__file__).resolve().parent / "strategy_adjustments.json"

# Limites de seguridad: la IA no puede pedir valores fuera de estos rangos.
# El techo de 0.80 (no 0.85) es deliberado: medido en producción (ago-2026),
# el bin de confianza 0.80 da 63.8% WR (+$25) mientras 0.85/0.90 caen a
# ~41-51% WR. Subir el umbral por encima de 0.80 ya no filtra ruido: solo
# recorta las entradas buenas de 0.80 y deja pasar contra-tendencia con
# confianza alta inflada que pierde.
MIN_CONF_RANGE = (0.55, 0.80)
EXPIRY_RANGE = (1, 10)
MAX_LESSONS = 60
MAX_PAUSE_HOURS = 24

_LOCK = threading.Lock()


def _default() -> Dict:
    return {
        "version": 1,
        "updated": time.time(),
        "cycle": 0,
        "min_confidence": None,
        "expiry_by_asset": {},
        "assets_pause": [],
        "lessons": [],
        "history": [],
    }


def _clamp_min_conf(v):
    if v is None:
        return None
    try:
        v = float(v)
    except Exception:
        return None
    lo, hi = MIN_CONF_RANGE
    return round(max(lo, min(hi, v)), 3)


def _clamp_expiry(v):
    try:
        v = int(round(float(v)))
    except Exception:
        return None
    lo, hi = EXPIRY_RANGE
    return max(lo, min(hi, v))


def load() -> Dict:
    """Carga la memoria. Si no existe o esta corrupta, devuelve defaults."""
    try:
        if not ADJUSTMENTS_PATH.exists():
            return _default()
        with open(ADJUSTMENTS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f) or {}
        # saneamiento
        d = _default()
        d.update({k: data.get(k) for k in d if k in data})
        d["min_confidence"] = _clamp_min_conf(d.get("min_confidence"))
        ea = {}
        if isinstance(d.get("expiry_by_asset"), dict):
            for k, v in d["expiry_by_asset"].items():
                ce = _clamp_expiry(v)
                if ce is not None:
                    ea[k] = ce
        d["expiry_by_asset"] = ea
        ap = d.get("assets_pause") or []
        d["assets_pause"] = [a for a in ap if isinstance(a, str)][:40]
        # expirar pausas viejas: cada pausa lleva ts; aqui solo limpiamos
        # las que superen MAX_PAUSE_HOURS (estructura opcional).
        d["lessons"] = (d.get("lessons") or [])[-MAX_LESSONS:]
        d["history"] = (d.get("history") or [])[-30:]
        return d
    except Exception:
        return _default()


def save(data: Dict) -> None:
    with _LOCK:
        try:
            data["updated"] = time.time()
            with open(ADJUSTMENTS_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[adjustments] ERROR guardando: {e}", flush=True)


def get_active_adjustments() -> Dict:
    """Snapshot que el bot live usa antes de operar (sinMetricas historicas)."""
    d = load()
    now = time.time()
    # Filtrar pausas expiradas: assets_pause puede ser lista de str
    # (pausa indefinida hasta proximo ciclo) o dict {asset: until_ts}.
    ap = d.get("assets_pause") or []
    if isinstance(ap, dict):
        active = [a for a, until in ap.items() if isinstance(until, (int, float)) and until > now]
    else:
        active = list(ap)
    # Expirar min_confidence de ciclos muy viejos (>): si updated > 48h, descartar override
    min_c = d.get("min_confidence")
    if min_c is not None and (now - d.get("updated", 0)) > 48 * 3600:
        min_c = None
    return {
        "min_confidence": min_c,
        "expiry_by_asset": d.get("expiry_by_asset") or {},
        "assets_pause": active,
        "lessons": d.get("lessons") or [],
        "cycle": d.get("cycle", 0),
        "updated": d.get("updated", 0),
    }


def export_for_prompt() -> Dict:
    """Snapshot resumido para incluir en el prompt del proximo ciclo IA."""
    d = load()
    return {
        "cycle": d.get("cycle", 0),
        "min_confidence": d.get("min_confidence"),
        "expiry_by_asset": d.get("expiry_by_asset"),
        "assets_pause": d.get("assets_pause"),
        "recent_lessons": (d.get("lessons") or [])[-8:],
        "recent_history": (d.get("history") or [])[-3:],
    }