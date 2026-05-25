"""
Configuración de activos por tipo y horario
Zona horaria: Colombia (UTC-5)
"""
from datetime import datetime, timezone, timedelta

# ─────────────────────────────────────────────────────────────────────────────
# ACTIVOS OTC - OPERAN 24/7
# ─────────────────────────────────────────────────────────────────────────────

ASSETS_OTC_24_7 = [
    # ── Forex OTC (24/7) ──
    "EURUSD-OTC", "GBPUSD-OTC", "AUDUSD-OTC", "USDJPY-OTC",
    "EURJPY-OTC", "EURGBP-OTC", "NZDUSD-OTC", "USDCAD-OTC",
    "USDCHF-OTC", "AUDJPY-OTC", "CADJPY-OTC", "CHFJPY-OTC",
    "EURAUD-OTC", "EURCAD-OTC", "EURCHF-OTC", "GBPAUD-OTC",
    "GBPCAD-OTC", "GBPCHF-OTC", "GBPJPY-OTC", "AUDCAD-OTC",
    "AUDCHF-OTC", "CADCHF-OTC", "AUDNZD-OTC", "EURNZD-OTC",
    "GBPNZD-OTC", "NZDCAD-OTC", "NZDJPY-OTC", "NZDCHF-OTC",
    "USDNOK-OTC", "USDSEK-OTC", "USDTRY-OTC", "USDPLN-OTC",
    "USDZAR-OTC", "USDSGD-OTC", "USDHKD-OTC", "USDINR-OTC",
    "USDMXN-OTC", "USDBRL-OTC", "USDCOP-OTC", "USDARS-OTC",
    "USDSAR-OTC", "USDAED-OTC", "USDNGN-OTC", "USDPHP-OTC",
    "USDIDR-OTC", "USDTHB-OTC", "EURTHB-OTC", "JPYTHB-OTC",
    "USDVND-OTC", "USDBDT-OTC", "USDCLP-OTC", "USDBOB-OTC",
    "USDDOP-OTC", "CHFNOK-OTC", "NOKJPY-OTC", "PENUSD-OTC",
    "USDXOF-OTC", "USDMYR-OTC",

    # ── Índices OTC ──
    "SP500-OTC", "USNDAQ100-OTC", "US30-OTC", "US2000-OTC",
    "FR40-OTC", "GER30-OTC", "UK100-OTC", "AUS200-OTC",
    "HK33-OTC", "EU50-OTC", "JP225-OTC", "SP35-OTC",

    # ── Materias Primas OTC ──
    "XAUUSD-OTC", "XAGUSD-OTC", "USOUSD-OTC", "UKOUSD-OTC",
    "XNGUSD-OTC", "XPTUSD-OTC", "XPDUSD-OTC",
    "COCOA-OTC", "COFFEE-OTC", "COTTON-OTC", "SUGAR-OTC",

    # ── Criptos OTC ──
    "ETHUSD-OTC", "XRPUSD-OTC", "LTCUSD-OTC", "BCHUSD-OTC",
    "SOLUSD-OTC", "LINKUSD-OTC", "DOTUSD-OTC", "SHIBUSD-OTC",
    "FLOKIUSD-OTC", "EOSUSD-OTC", "ATOMUSD-OTC", "NEARUSD-OTC",
    "LUNA-OTC",

    # ── Acciones OTC ──
    "GOOGLE-OTC", "AMAZON-OTC", "TESLA-OTC", "APPLE-OTC",
    "MSFT-OTC", "NVDA-OTC", "FB-OTC", "BIDU-OTC",
    "ALIBABA-OTC", "JPM-OTC", "GS-OTC", "PLTR-OTC",
    "SNAP-OTC", "INTEL-OTC", "CITI-OTC", "NIKE-OTC",
    "COKE-OTC", "MCDON-OTC", "AIG-OTC", "MORSTAN-OTC",
]

# ─────────────────────────────────────────────────────────────────────────────
# ACTIVOS PTC (NORMAL) - SOLO HORARIO MAÑANA
# ─────────────────────────────────────────────────────────────────────────────

ASSETS_PTC_MORNING = [
    # Pares Forex normales (solo mañana 08:00-12:00 Colombia)
    "EURUSD",
    "GBPUSD",
    "AUDUSD",
    "EURJPY",
    "USDJPY",
    "EURGBP",
    "NZDUSD",
    "USDCAD",
    "USDCHF",
    # Índices normales
    "SPX",
    "DAX",
    "FTSE",
    "NIKKEI",
]

# ─────────────────────────────────────────────────────────────────────────────
# BINARY OPTIONS OTC - OPORTUNIDADES ESPECIALES
# ─────────────────────────────────────────────────────────────────────────────

ASSETS_BO_OTC = [
    # Se activarán cuando el motor detecte patrones especiales
    "EURUSD-OTC-BO",
    "GBPUSD-OTC-BO",
    "AUDUSD-OTC-BO",
    "GOLD-OTC-BO",
]

# ─────────────────────────────────────────────────────────────────────────────
# HORARIOS (Colombia UTC-5)
# ─────────────────────────────────────────────────────────────────────────────

COLOMBIA_TZ = timezone(timedelta(hours=-5))

HORARIO_MANANA = {
    "inicio": 8,      # 08:00 hrs
    "fin": 12,        # 12:00 hrs
    "nombre": "Mañana (08:00-12:00)"
}

HORARIO_TARDE = {
    "inicio": 12,     # 12:00 hrs
    "fin": 18,        # 18:00 hrs
    "nombre": "Tarde (12:00-18:00)"
}

HORARIO_NOCHE = {
    "inicio": 18,     # 18:00 hrs
    "fin": 24,        # 00:00 hrs
    "nombre": "Noche (18:00-00:00)"
}

HORARIO_MADRUGADA = {
    "inicio": 0,      # 00:00 hrs
    "fin": 8,         # 08:00 hrs
    "nombre": "Madrugada (00:00-08:00)"
}

# ─────────────────────────────────────────────────────────────────────────────
# FUNCIONES AUXILIARES
# ─────────────────────────────────────────────────────────────────────────────

def get_current_time_colombia():
    """Obtiene la hora actual en Colombia."""
    return datetime.now(COLOMBIA_TZ)

def get_current_hour():
    """Obtiene la hora actual (0-23) en Colombia."""
    return get_current_time_colombia().hour

def es_horario_manana():
    """Verifica si es horario de mañana (08:00-12:00)."""
    hora = get_current_hour()
    return HORARIO_MANANA["inicio"] <= hora < HORARIO_MANANA["fin"]

def es_horario_otc():
    """Verifica si es horario para operar OTC (24/7)."""
    return True  # OTC opera siempre

def get_activos_activos():
    """
    Devuelve los activos que deben ser operados AHORA.
    
    Returns:
        dict: {
            "otc_24_7": [...],      # Siempre activos
            "ptc_morning": [...],   # Solo si es mañana
            "bo_otc": [...]         # Oportunidades especiales
        }
    """
    activos = {
        "otc_24_7": ASSETS_OTC_24_7,
        "ptc_morning": [],
        "bo_otc": ASSETS_BO_OTC,
    }
    
    # Añadir PTC si es horario de mañana
    if es_horario_manana():
        activos["ptc_morning"] = ASSETS_PTC_MORNING
    
    return activos

def get_lista_completa_activos():
    """Devuelve todos los activos (OTC + PTC)."""
    return {
        "otc_24_7": ASSETS_OTC_24_7,
        "ptc_morning": ASSETS_PTC_MORNING,
        "bo_otc": ASSETS_BO_OTC,
    }

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURACIÓN DE SENSIBILIDAD POR TIPO DE ACTIVO
# ─────────────────────────────────────────────────────────────────────────────

CONFIG_SENSIBILIDAD = {
    "otc_24_7": {
        "min_zone_strength": 0.25,
        "min_hold_rate": 0.10,
        "ia_min_score": 20,
        "expiration_default": 180,
        "min_confidence": 0.20,
    },
    "ptc_morning": {
        "min_zone_strength": 0.30,
        "min_hold_rate": 0.15,
        "ia_min_score": 25,
        "expiration_default": 300,
        "min_confidence": 0.25,
    },
    "bo_otc": {
        "min_zone_strength": 0.35,
        "min_hold_rate": 0.15,
        "ia_min_score": 30,
        "expiration_default": 120,
        "min_confidence": 0.30,
    },
}

def get_config_sensibilidad(tipo_activo):
    """Obtiene la configuración de sensibilidad para un tipo de activo."""
    return CONFIG_SENSIBILIDAD.get(tipo_activo, CONFIG_SENSIBILIDAD["otc_24_7"])

# ─────────────────────────────────────────────────────────────────────────────
# RESUMEN
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 80)
    print("CONFIGURACIÓN DE ACTIVOS - EXNOVA BOT")
    print("=" * 80)
    print(f"\nZona horaria: Colombia (UTC-5)")
    print(f"Hora actual: {get_current_time_colombia().strftime('%H:%M:%S')}")
    print(f"Es horario mañana: {es_horario_manana()}")
    print(f"\nOTC 24/7: {len(ASSETS_OTC_24_7)} activos")
    print(f"PTC Mañana: {len(ASSETS_PTC_MORNING)} activos (solo 08:00-12:00)")
    print(f"BO OTC: {len(ASSETS_BO_OTC)} activos (oportunidades especiales)")
    print(f"\nActivos activos AHORA:")
    activos = get_activos_activos()
    print(f"  - OTC 24/7: {len(activos['otc_24_7'])}")
    print(f"  - PTC Mañana: {len(activos['ptc_morning'])}")
    print(f"  - BO OTC: {len(activos['bo_otc'])}")
    print("=" * 80)
