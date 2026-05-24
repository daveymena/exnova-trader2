"""
Market Session Analyzer — Detecta la sesión de mercado activa y adapta el bot
El bot opera 24/7 pero ajusta su comportamiento según la sesión:
- Sesión Asiática (Tokyo): 00:00-09:00 UTC — baja volatilidad, rangos estrechos
- Sesión Europea (Londres): 07:00-16:00 UTC — alta volatilidad, tendencias claras
- Sesión Americana (NY): 12:00-21:00 UTC — máxima volatilidad, movimientos fuertes
- Overlap Londres-NY: 12:00-16:00 UTC — mejor momento del día
- Mercado OTC: opera 24/7 pero sigue patrones de volatilidad similares
"""
import time
from datetime import datetime, timezone
from typing import Dict, Tuple


class MarketSession:
    """
    Detecta la sesión activa y ajusta parámetros del bot en consecuencia.
    El bot NUNCA se detiene — solo ajusta su agresividad según la sesión.
    """

    # Sesiones en horas UTC
    SESSIONS = {
        "ASIA":    {"start": 0,  "end": 9,  "label": "Asia/Tokyo"},
        "EUROPE":  {"start": 7,  "end": 16, "label": "Londres"},
        "AMERICA": {"start": 12, "end": 21, "label": "Nueva York"},
        "PACIFIC": {"start": 21, "end": 24, "label": "Pacífico/Sydney"},
    }

    # Parámetros por sesión — el bot se adapta, no se detiene
    SESSION_PARAMS = {
        "OVERLAP_EU_US": {
            # 12:00-16:00 UTC — mejor momento, máxima liquidez
            "min_confidence":    0.50,
            "zone_tolerance":    0.0008,   # muy preciso
            "min_zone_strength": 0.55,
            "expiration_mult":   1.0,
            "trade_freq":        "HIGH",
            "description":       "Overlap Londres-NY: máxima liquidez y movimientos claros",
        },
        "EUROPE": {
            # 07:00-12:00 UTC — buena volatilidad
            "min_confidence":    0.52,
            "zone_tolerance":    0.0010,
            "min_zone_strength": 0.50,
            "expiration_mult":   1.0,
            "trade_freq":        "HIGH",
            "description":       "Sesión Europea: buena volatilidad y tendencias",
        },
        "AMERICA": {
            # 16:00-21:00 UTC — post-overlap, aún activo
            "min_confidence":    0.53,
            "zone_tolerance":    0.0010,
            "min_zone_strength": 0.52,
            "expiration_mult":   1.0,
            "trade_freq":        "MEDIUM",
            "description":       "Sesión Americana: activo pero más errático post-overlap",
        },
        "ASIA": {
            # 00:00-07:00 UTC — baja volatilidad, rangos estrechos
            # SOLO trades de MUY alta calidad (menos liquidez = spreads más amplios)
            "min_confidence":    0.55,
            "zone_tolerance":    0.0012,
            "min_zone_strength": 0.60,
            "expiration_mult":   2.0,
            "trade_freq":        "VERY_LOW",
            "description":       "Sesión Asiática: baja volatilidad, solo mejores setups",
        },
        "PACIFIC": {
            # 21:00-24:00 UTC — transicion baja liquidez
            "min_confidence":    0.52,
            "zone_tolerance":    0.0012,
            "min_zone_strength": 0.55,
            "expiration_mult":   1.5,
            "trade_freq":        "LOW",
            "description":       "Sesion Pacifico: baja liquidez, selectivo",
        },
        "DEAD": {
            # Mercado completamente muerto (raro en OTC pero posible)
            "min_confidence":    0.55,
            "zone_tolerance":    0.0010,
            "min_zone_strength": 0.55,
            "expiration_mult":   2.5,
            "trade_freq":        "VERY_LOW",
            "description":       "Mercado sin volatilidad: pausar hasta que vuelva",
        },
    }

    def get_current_session(self) -> Tuple[str, Dict]:
        """
        Detecta la sesión actual basada en UTC.
        Retorna (session_name, params).
        El bot SIEMPRE opera — solo cambia los parámetros.
        """
        now_utc = datetime.now(timezone.utc)
        hour = now_utc.hour + now_utc.minute / 60.0

        # Overlap Londres-NY es el mejor momento
        if 12.0 <= hour < 16.0:
            return "OVERLAP_EU_US", self.SESSION_PARAMS["OVERLAP_EU_US"]

        # Sesión Europea (pre-overlap)
        if 7.0 <= hour < 12.0:
            return "EUROPE", self.SESSION_PARAMS["EUROPE"]

        # Sesión Americana (post-overlap)
        if 16.0 <= hour < 21.0:
            return "AMERICA", self.SESSION_PARAMS["AMERICA"]

        # Sesión Pacífico/Sydney
        if 21.0 <= hour < 24.0 or hour < 1.0:
            return "PACIFIC", self.SESSION_PARAMS["PACIFIC"]

        # Sesión Asiática (hora más tranquila)
        return "ASIA", self.SESSION_PARAMS["ASIA"]

    def get_session_quality(self) -> float:
        """
        Retorna un score 0-1 de la calidad de la sesión actual.
        1.0 = overlap (mejor), 0.4 = Asia profunda (peor pero operable)
        """
        session, _ = self.get_current_session()
        quality_map = {
            "OVERLAP_EU_US": 1.0,
            "EUROPE":        0.85,
            "AMERICA":       0.75,
            "PACIFIC":       0.55,
            "ASIA":          0.45,
            "DEAD":          0.20,
        }
        return quality_map.get(session, 0.5)

    def get_adaptive_params(self, base_confidence: float = 0.50,
                             atr_pct: float = 0.01) -> Dict:
        """
        Retorna parámetros adaptados a la sesión actual Y a la volatilidad real.
        Combina sesión + volatilidad medida para máxima adaptación.
        """
        session_name, session_params = self.get_current_session()

        # Detectar mercado muerto por ATR bajo
        if atr_pct < 0.0003:  # menos de 3 pips de ATR promedio
            return session_name, self.SESSION_PARAMS["DEAD"]

        # Ajuste fino por volatilidad dentro de la sesión
        params = dict(session_params)

        if atr_pct > 0.0025:
            # Alta volatilidad: ser más preciso en la zona
            params["zone_tolerance"] = max(0.0006, params["zone_tolerance"] * 0.8)
            params["min_confidence"] = min(0.65, params["min_confidence"] + 0.03)
        elif atr_pct < 0.0008:
            # Baja volatilidad: ampliar tolerancia de zona
            params["zone_tolerance"] = min(0.0020, params["zone_tolerance"] * 1.3)
            params["expiration_mult"] = min(2.5, params["expiration_mult"] * 1.2)

        return session_name, params

    def get_status_display(self) -> str:
        """Para mostrar en el dashboard"""
        session_name, params = self.get_current_session()
        now_utc = datetime.now(timezone.utc)
        quality = self.get_session_quality()
        quality_bar = "█" * int(quality * 5) + "░" * (5 - int(quality * 5))
        freq = params.get("trade_freq", "MEDIUM")
        freq_colors = {
            "HIGH": "green", "MEDIUM": "yellow",
            "LOW": "orange1", "VERY_LOW": "red"
        }
        return (
            f"{session_name} [{now_utc.strftime('%H:%M')} UTC] "
            f"Calidad:{quality_bar} Freq:{freq}"
        )

    def should_adjust_expiration(self, base_expiration_seconds: int) -> int:
        """Ajusta la expiración según la sesión actual"""
        _, params = self.get_current_session()
        mult = params.get("expiration_mult", 1.0)
        adjusted = int(base_expiration_seconds * mult)
        # Límites: mínimo 60s, máximo 300s para binarias
        return max(60, min(300, adjusted))


# Singleton
_session: MarketSession = None


def get_market_session() -> MarketSession:
    global _session
    if _session is None:
        _session = MarketSession()
    return _session
