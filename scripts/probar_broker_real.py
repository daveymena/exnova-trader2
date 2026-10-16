#!/usr/bin/env python3
"""Prueba de conexion contra el broker REAL (cuenta PRACTICE).

Es el paso que da el usuario: con credenciales en .env, esto conecta a
Exnova, descarga un rato de velas REALES y ejecuta la auditoria sobre ellas.
No envia ninguna orden: solo mira el mercado.

Si no hay credenciales, lo dice y sale con codigo 1.

Uso:
    python scripts/probar_broker_real.py
    python scripts/probar_broker_real.py --assets EURUSD-OTC,GBPUSD-OTC --velas 200
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--assets", default="EURUSD-OTC,GBPUSD-OTC,USDJPY-OTC")
    ap.add_argument("--velas", type=int, default=200)
    ap.add_argument("--segundos", type=float, default=20.0,
                    help="cuanto tiempo observar velas en vivo llegando")
    args = ap.parse_args()

    email = os.getenv("EXNOVA_EMAIL", "").strip()
    password = os.getenv("EXNOVA_PASSWORD", "").strip()

    print("=" * 78)
    print("PRUEBA CONTRA BROKER REAL - CUENTA PRACTICE")
    print("=" * 78)

    if not email or not password or email == "tu_email@ejemplo.com":
        print("\nFALTAN CREDENCIALES.")
        print("Crear .env en la raiz del repo con:")
        print()
        print("    ACCOUNT_TYPE=PRACTICE")
        print("    EXNOVA_EMAIL=tu_correo_real")
        print("    EXNOVA_PASSWORD=tu_clave_real")
        print()
        print("PRACTICE es la cuenta demo: no arriesga dinero real.")
        print("El bot NUNCA pasa a REAL sin REAL_TRADING_ENABLED=true.")
        return 1

    from app.services.exnova_broker import ExnovaBroker, ExnovaAPI
    if ExnovaAPI is None:
        print("\nLa libreria exnovaapi no esta disponible.")
        print("Deberia estar vendorizada en bot/exnovaapi/.")
        return 1

    broker = ExnovaBroker(email=email, password=password, account_type="PRACTICE")
    print(f"\nConectando a Exnova como {email} (PRACTICE)...")
    if not broker.connect():
        print("\nNO SE PUDO CONECTAR. Revisar credenciales y red.")
        return 1

    print(f"\nConectado. Balance demo: ${broker.get_balance():.2f}")
    print("(Es cuenta de practica: este dinero no es real.)\n")

    assets = [a.strip() for a in args.assets.split(",") if a.strip()]
    open_assets = broker.get_open_assets(min_profit=75)
    if open_assets:
        disponibles = {a["name"] for a in open_assets}
        print(f"Activos abiertos en el broker: {len(disponibles)}")
        faltan = [a for a in assets if a not in disponibles]
        if faltan:
            print(f"  OJO, no encontrados: {faltan}")
            print(f"  Ejemplos disponibles: {sorted(disponibles)[:12]}")

    from app.data.schemas import Timeframe

    print(f"\nDescargando {args.velas} velas M1 de cada activo...")
    series = {}
    for asset in assets:
        candles = broker.get_candles_as_schema(asset, Timeframe.M1, args.velas)
        if not candles:
            print(f"  {asset}: SIN DATOS")
            continue
        series[asset] = candles
        c = candles
        variacion = (c[-1].close - c[0].close) / c[0].close * 100
        rangos = [x.range for x in c]
        print(f"  {asset}: {len(c)} velas, "
              f"{c[0].open_time:%H:%M} -> {c[-1].open_time:%H:%M}, "
              f"precio {c[-1].close:.5f}, variacion {variacion:+.3f}%, "
              f"rango medio {sum(rangos)/len(rangos):.5f}")

    if not series:
        print("\nNingun activo devolvio velas. El mercado puede estar cerrado")
        print("o los nombres de activo no coinciden con los del broker.")
        broker.disconnect()
        return 1

    print(f"\nObservando velas en vivo durante {args.segundos:.0f}s...")
    print("(Asi se ve si el feed llega de verdad y a que ritmo.)")
    vistos = 0
    ultimo = {}
    fin = time.time() + args.segundos
    while time.time() < fin:
        for asset in series:
            candles = broker.get_candles_as_schema(asset, Timeframe.M1, 2)
            if not candles:
                continue
            llave = candles[-1].open_time
            if ultimo.get(asset) != llave:
                ultimo[asset] = llave
                vistos += 1
                if vistos <= 12:
                    print(f"  {asset} nueva vela {llave:%H:%M:%S} "
                          f"close={candles[-1].close:.5f}")
        time.sleep(1)

    print(f"\nVelas nuevas observadas: {vistos}")
    if vistos == 0:
        print("OJO: ninguna vela nueva en ese tiempo. Puede que el mercado")
        print("este cerrado (finde) o que el activo no cotice ahora.")

    # Auditar sobre los datos reales que acabamos de bajar
    print("\n" + "=" * 78)
    print("AUDITORIA SOBRE ESTAS VELAS REALES")
    print("=" * 78)
    import scripts.research_strategy_audit as audit
    for asset, candles in series.items():
        m15 = audit.resample(candles, Timeframe.M15, 15)
        m5 = audit.resample(candles, Timeframe.M5, 5)
        from app.agents.market_regime_agent import MarketRegimeAgent
        from app.strategies.breakout_direct import BreakoutDirectStrategy
        from app.strategies.sr_bounce import SRBounceStrategy
        from app.strategies.mean_reversion import MeanReversionStrategy
        regime_agent = MarketRegimeAgent()
        estrategias = {
            "breakout_direct": BreakoutDirectStrategy(),
            "sr_bounce": SRBounceStrategy(),
            "mean_reversion": MeanReversionStrategy(),
        }
        tally = {}
        for i in range(80, len(candles)):
            idx15, idx5 = i // 15 + 1, i // 5 + 1
            c15 = m15[max(0, idx15 - 60): idx15]
            c5 = m5[max(0, idx5 - 120): idx5]
            c1 = candles[max(0, i + 1 - 400): i + 1]
            regime = regime_agent.classify(c15, asset).regime.value
            for nombre, strat in estrategias.items():
                try:
                    sig = strat.evaluate(c15, c5, c1, asset)
                except Exception:
                    continue
                d = sig.get("direction")
                if d is None or d.value == "no_trade":
                    continue
                bars = max(1, round((sig.get("expiry") or 180) / 60))
                j = i + bars
                if j >= len(candles):
                    continue
                if candles[j].close == candles[i].close:
                    continue
                won = (candles[j].close > candles[i].close
                       if d.value == "call" else candles[j].close < candles[i].close)
                k = (nombre, d.value, regime)
                tally.setdefault(k, [0, 0])
                tally[k][1] += 1
                tally[k][0] += 1 if won else 0

        if not tally:
            print(f"\n{asset}: ninguna estrategia genero senales con estas velas.")
            continue
        print(f"\n{asset}:")
        print(f"  {'estrategia':<18}{'dir':<6}{'regimen':<14}{'n':>5}{'WR%':>8}")
        for (nombre, d, regime), (wins, total) in sorted(tally.items()):
            wr = wins / total * 100 if total else 0
            marca = "" if total < 15 else ("  <-- edge" if wr > 54 else "  <-- pierde")
            print(f"  {nombre:<18}{d:<6}{regime:<14}{total:>5}{wr:>7.1f}%{marca}")

    broker.disconnect()
    print("\n" + "=" * 78)
    print("Desconectado. No se envio ninguna orden.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
