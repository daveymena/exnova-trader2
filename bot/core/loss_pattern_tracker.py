# -*- coding: utf-8 -*-
"""
Loss Pattern Tracker — Memoria de pérdidas que evita repetir errores.

El TradeEvaluator ya IDENTIFICA por qué pierde cada operación (causa primaria
+ condiciones del mercado). Este módulo GUARDA esas huellas y las usa para
BLOQUEAR operaciones futuras que coincidan con patrones de pérdida repetidos.

Filosofía: si un tipo de pérdida se repite 3+ veces en las últimas 50
operaciones, algo está sistemáticamente mal. No es estadística, es lógica:
el mercado está diciendo "no entres aquí" y hay que escuchar.

Regla de oro: solo bloquea en paper/practice. NUNCA activa dinero real.
"""
from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "loss_patterns.json"

# ── Causas que el TradeEvaluator detecta ──────────────────────────────────
BLOCKABLE_CAUSES = {
    "counter_trend",      # Operar contra tendencia
    "bad_market_phase",   # Mercado muerto/volátil errático
    "zone_too_weak",      # Zona débil
    "no_rejection_wick",  # Sin rechazo visible
    "rsi_not_extreme",    # RSI no en zona extrema
    "mtf_not_aligned",    # Timeframes en conflicto
    "premature_entry",    # Entrada antes de confirmación
}

# Cuántas veces debe repetirse un patrón para bloquear
MIN_LOSSES_TO_BLOCK = 3

# Ventana de análisis (últimas N operaciones)
WINDOW_SIZE = 50


@dataclass
class LossFingerprint:
    """Huella de una pérdida: causa + condiciones clave del mercado."""
    cause: str
    asset: str
    direction: str
    rsi_range: str          # "oversold" (<35), "neutral" (35-65), "overbought" (>65)
    trend: str              # "aligned", "counter", "neutral"
    zone_strength: str      # "weak" (<0.5), "medium" (0.5-0.7), "strong" (>0.7)
    phase: str              # trending, ranging, dead, volatile_ranging, etc.
    pattern_type: str       # "reversal", "continuation", "none"
    timestamp: float = field(default_factory=time.time)

    def key(self) -> str:
        """Clave única del patrón de pérdida."""
        return f"{self.cause}|{self.rsi_range}|{self.trend}|{self.zone_strength}|{self.phase}"


class LossPatternTracker:
    """
    Rastrea patrones de pérdida y bloquea operaciones que los replican.
    """

    def __init__(self, path: str | Path | None = None, min_losses: int = MIN_LOSSES_TO_BLOCK):
        self.path = Path(path) if path else DEFAULT_PATH
        self.min_losses = min_losses
        self.losses: deque[LossFingerprint] = deque(maxlen=WINDOW_SIZE)
        self.blocked_keys: dict[str, int] = {}  # key -> count
        self._lock = threading.RLock()
        self._load()

    def _load(self) -> None:
        try:
            if self.path.exists():
                data = json.loads(self.path.read_text(encoding="utf-8"))
                for item in data.get("losses", []):
                    self.losses.append(LossFingerprint(**item))
                self.blocked_keys = data.get("blocked_keys", {})
        except Exception:
            pass

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "losses": [
                {k: v for k, v in fp.__dict__.items()}
                for fp in self.losses
            ],
            "blocked_keys": self.blocked_keys,
            "updated_at": time.time(),
        }
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def _classify_rsi(self, rsi: float | None) -> str:
        if rsi is None:
            return "unknown"
        if rsi < 35:
            return "oversold"
        if rsi > 65:
            return "overbought"
        return "neutral"

    def _classify_zone(self, zs: float | None) -> str:
        if zs is None:
            return "unknown"
        if zs < 0.5:
            return "weak"
        if zs > 0.7:
            return "strong"
        return "medium"

    def _classify_trend(self, conditions: dict) -> str:
        if conditions.get("counter_trend"):
            return "counter"
        if conditions.get("trend_aligned"):
            return "aligned"
        return "neutral"

    def _classify_pattern(self, conditions: dict) -> str:
        if conditions.get("pattern_strong"):
            return "continuation" if conditions.get("trend_aligned") else "reversal"
        return "none"

    def record_loss(self, diagnosis: dict, conditions: dict) -> dict:
        """
        Registra una pérdida y su huella. Devuelve info útil para logging.
        """
        cause = diagnosis.get("primary_cause", "unknown")
        if cause not in BLOCKABLE_CAUSES:
            return {"recorded": False, "cause": cause}

        fp = LossFingerprint(
            cause=cause,
            asset=diagnosis.get("asset", "?"),
            direction=diagnosis.get("direction", "?"),
            rsi_range=self._classify_rsi(conditions.get("rsi", conditions.get("momentum", {}).get("rsi_m1"))),
            trend=self._classify_trend(conditions),
            zone_strength=self._classify_zone(
                conditions.get("zone_strength", conditions.get("zone_context", {}).get("zone_strength"))
            ),
            phase=conditions.get("market_phase", conditions.get("phase", "unknown")),
            pattern_type=self._classify_pattern(conditions),
        )

        with self._lock:
            self.losses.append(fp)
            key = fp.key()
            self.blocked_keys[key] = self.blocked_keys.get(key, 0) + 1
            self._save()

        count = self.blocked_keys.get(key, 0)
        return {
            "recorded": True,
            "cause": cause,
            "pattern_key": key,
            "repeat_count": count,
            "blocked": count >= self.min_losses,
        }

    def check_conditions(self, conditions: dict, signal: dict | None = None) -> dict:
        """
        Verifica si las condiciones actuales coinciden con un patrón de
        pérdida conocido. Si el patrón se ha repetido >= min_losses veces,
        bloquea la operación.

        Devuelve:
            {"allowed": bool, "reason": str, "blocked_cause": str|None,
             "loss_count": int}
        """
        # Clasificar las condiciones actuales
        current_rsi = self._classify_rsi(
            signal.get("rsi") if signal else conditions.get("rsi", conditions.get("momentum", {}).get("rsi_m1"))
        )
        current_trend = self._classify_trend(conditions)
        current_zone = self._classify_zone(
            conditions.get("zone_strength", conditions.get("zone_context", {}).get("zone_strength"))
        )
        current_phase = conditions.get("market_phase", conditions.get("phase", "unknown"))
        current_pattern = self._classify_pattern(conditions)

        with self._lock:
            # Buscar en las pérdidas recientes si alguna coincide
            for fp in self.losses:
                if (fp.rsi_range == current_rsi or current_rsi == "unknown" or
                    fp.rsi_range == "unknown"):
                    # No comparar RSI si es desconocido
                    if (fp.trend == current_trend and
                        fp.zone_strength == current_zone and
                        fp.phase == current_phase):
                        key = fp.key()
                        count = self.blocked_keys.get(key, 0)
                        if count >= self.min_losses:
                            return {
                                "allowed": False,
                                "reason": (
                                    f"Patrón de pérdida conocido: '{fp.cause}' "
                                    f"repetido {count} veces en las últimas "
                                    f"{len(self.losses)} operaciones. "
                                    f"Mercado: RSI={current_rsi}, zona={current_zone}, "
                                    f"tendencia={current_trend}, fase={current_phase}. "
                                    f"El mercado indica que NO se debe entrar aquí."
                                ),
                                "blocked_cause": fp.cause,
                                "loss_count": count,
                            }

        return {"allowed": True, "reason": "Sin patrón de bloqueo conocido",
                "blocked_cause": None, "loss_count": 0}

    def summary(self) -> dict:
        """Resumen de patrones de pérdida activos."""
        with self._lock:
            active = {k: v for k, v in self.blocked_keys.items()
                     if v >= self.min_losses}
            return {
                "total_losses_tracked": len(self.losses),
                "blocked_patterns": len(active),
                "blocked_details": active,
                "min_losses_to_block": self.min_losses,
            }

    def clear_pattern(self, key: str) -> bool:
        """Limpia un patrón de bloqueo específico (para re-entrenar)."""
        with self._lock:
            if key in self.blocked_keys:
                del self.blocked_keys[key]
                self._save()
                return True
            return False

    def clear_all(self) -> int:
        """Limpia todos los patrones de bloqueo."""
        with self._lock:
            count = len(self.blocked_keys)
            self.blocked_keys.clear()
            self._save()
            return count


# Instancia global
_instance: LossPatternTracker | None = None
_instance_lock = threading.Lock()


def get_loss_tracker(path: str | Path | None = None) -> LossPatternTracker:
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = LossPatternTracker(path)
        return _instance
