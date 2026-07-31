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

# Nombres VERIFICADOS contra la API el 2026-07-31 con scripts/check_assets.py.
# La lista anterior ("EURUSD", "GBPUSD", "SPX", "DAX", "FTSE", "NIKKEI", ...)
# no existia: ninguno de esos 13 tickers es reconocido por el broker, por eso
# toda operacion sobre mercado real fallaba y el bot caia siempre en OTC.
#
# HALLAZGO IMPORTANTE: el broker NO ofrece ningun par de forex real como opcion
# binaria. Solo existen en su version -OTC sintetica. Lo unico real disponible
# son indices bursatiles, indices de divisas y ETHUSD.
#
# Verificar de nuevo con:  python scripts/check_assets.py --real-only

# Indices bursatiles reales: disponibles en turbo (1-5 min) Y en binary.
ASSETS_REAL_TURBO = [
    "USSPX500:N",     # S&P 500
    "USNDAQ100:N",    # Nasdaq 100
    "US30:N",         # Dow Jones
    "US2000:N",       # Russell 2000
    "JAPAN225:N",     # Nikkei 225
]

# Solo disponibles como binary (expiraciones largas), no en turbo.
ASSETS_REAL_BINARY_ONLY = [
    "DXY",            # indice del dolar
    "EXY",            # indice del euro
    "AXY",            # indice del dolar australiano
    "BXY",            # indice de la libra
    "ETHUSD-op",      # Ethereum, mercado real
]

# Mantiene el nombre historico por compatibilidad con run_live.py, pero ya no
# depende de un horario inventado: estos indices cotizan casi 24/5 y quien
# decide si estan abiertos es el broker, no una constante del codigo.
ASSETS_PTC_MORNING = list(ASSETS_REAL_TURBO)

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
# BLACKLIST - ACTIVOS CON PEOR RENDIMIENTO HISTÓRICO
# Basado en análisis de 173 trades: estos activos tienen WR < 40% y PnL negativo
# ─────────────────────────────────────────────────────────────────────────────

ASSETS_BLACKLIST = {
    # Peores activos (PnL más negativo, WR < 50%)
    "SUGAR-OTC",        # -$52.23, 33.3% WR (6t)
    "AUDCAD-OTC",       # -$44.59, 14.3% WR (7t)
    "APPLE-OTC",        # -$41.03, 50.0% WR (4t)
    "USDAED-OTC",       # -$38.27, 0% WR (2t)
    "AUDNZD-OTC",       # -$30.32, 44.4% WR (9t)
    "COFFEE-OTC",       # -$25.30, 0% WR (3t)
    "CHFNOK-OTC",       # -$26.22, 0% WR (3t)
    "FB-OTC",           # -$24.48, 0% WR (2t)
    "ETHUSD-OTC",       # -$23.19, 0% WR (2t)
    "ALIBABA-OTC",      # -$21.75, 0% WR (2t)
    "USDCHF-OTC",       # -$21.06, 0% WR (2t)
    "NZDCHF-OTC",       # -$20.03, 0% WR (2t)
    "USDPHP-OTC",       # -$19.87, 25.0% WR (4t)
    "INTEL-OTC",        # -$18.56, 0% WR (2t)
    "CITI-OTC",         # -$18.59, 0% WR (2t)
    "USDZAR-OTC",       # -$18.61, 0% WR (2t)
    "GER30-OTC",        # -$18.69, 25.0% WR (4t)
    "JPM-OTC",          # -$18.79, 0% WR (2t)
    "XAUUSD-OTC",       # -$18.91, 33.3% WR (6t)
    "USDPLN-OTC",       # -$4.21, 50.0% WR (6t)
}

BAD_PATTERNS = {
    "engulfing_bearish",  # 20.0% WR (2/10), -$83.85 PnL — PEOR PATRÓN
    "doji",               # 0% WR (0/1), -$10.05 PnL
    "hammer",             # 42.9% WR (3/7), -$13.62 PnL
    "engulfing_bullish",  # 54.5% WR (6/11), -$6.41 PnL (borde)
}

# ─────────────────────────────────────────────────────────────────────────────
# REAL_WHITELIST - ACTIVOS Y PATRONES QUE SÍ FUNCIONAN (para cuenta REAL)
# Basado en análisis de trades reales. Solo lo que tiene WR > 60%
# ─────────────────────────────────────────────────────────────────────────────

REAL_ASSETS_WHITELIST = {
    # ── Fuertes (PnL > $10, WR ≥ 60%) ──
    "EURUSD-OTC",    # 60.0% WR (6/10), +$12.85 PnL
    "USDJPY-OTC",    # 62.5% WR (5/8), +$11.32 PnL
    "GBPAUD-OTC",    # 80.0% WR (4/5), +$20.19 PnL
    "USOUSD-OTC",    # 80.0% WR (4/5), +$19.34 PnL
    "AMAZON-OTC",    # 62.5% WR (5/8), +$22.30 PnL
    "GOOGLE-OTC",    # 80.0% WR (4/5), +$21.05 PnL
    "TESLA-OTC",     # 75.0% WR (3/4), +$20.95 PnL
    "XAGUSD-OTC",    # 75.0% WR (3/4), +$13.74 PnL
    "EURNZD-OTC",    # 75.0% WR (3/4), +$12.37 PnL
    "EURCAD-OTC",    # 60.0% WR (3/5), +$9.34 PnL
    "AUDJPY-OTC",    # 60.0% WR (3/5), +$7.96 PnL
    "NZDJPY-OTC",    # 62.5% WR (5/8), +$1.73 PnL
    # ── Sólidos (WR > 50%, PnL positivo) ──
    "AUDUSD-OTC",    # 66.7% WR (2/3), +$6.72 PnL
    "GBPCAD-OTC",    # 66.7% WR (2/3), +$5.54 PnL
    "GBPNZD-OTC",    # 50.0% WR (3/6), +$4.07 PnL
    "GBPUSD-OTC",    # 100% WR (1/1), +$7.33 PnL
}

REAL_PATTERNS_ALLOWED = {
    "pin_bar_bullish",   # 68.2% WR (15/22), +$64.00 PnL — MEJOR PATRÓN
    "shooting_star",     # 60.0% WR (3/5), +$6.35 PnL
    "pin_bar_bearish",   # 54.5% WR (24/44), -$21.04 PnL
    "none",              # 54.1% WR (98/181), -$48.00 PnL
}

# Zona strength para REAL - SIN techo máximo (el motor da ZS~1.00)
# Solo filtramos piso mínimo: zonas débiles < 0.70 evitan pérdidas
REAL_ZONE_STRENGTH_MIN = 0.60
REAL_ZONE_STRENGTH_MAX = 1.00

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

def get_activos_activos(filter_blacklist=True):
    """
    Devuelve los activos que deben ser operados AHORA.
    
    Args:
        filter_blacklist: Si True, excluye activos en ASSETS_BLACKLIST
    
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
    
    # Los indices reales cotizan casi 24/5, no solo de 08:00 a 12:00. La ventana
    # de 4 horas que habia aqui era una constante inventada que, combinada con
    # los tickers erroneos, hacia imposible operar mercado real.
    # Quien decide si un activo esta abierto es el broker: ver
    # bot/core/asset_discovery.py y scripts/check_assets.py.
    activos["ptc_morning"] = ASSETS_PTC_MORNING
    
    # Filtrar blacklist si se solicita
    if filter_blacklist:
        for key in activos:
            activos[key] = [a for a in activos[key] if a not in ASSETS_BLACKLIST]
    
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
