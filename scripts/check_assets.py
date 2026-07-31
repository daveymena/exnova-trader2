# -*- coding: utf-8 -*-
"""
Diagnostico de activos: le pregunta al BROKER que hay abierto ahora mismo,
en vez de asumirlo desde una lista fija.

Responde a la pregunta "por que solo me deja operar OTC": muestra, por tipo de
instrumento (turbo / binary / digital), que activos estan abiertos, cuales son
de mercado real y cual es el payout de cada uno.

Uso:
    python scripts/check_assets.py
    python scripts/check_assets.py --real-only
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "bot"))

# Tipos de opcion binaria que ofrece la plataforma.
#   turbo   -> expiraciones cortas (1-5 min), es lo que usa el bot
#   binary  -> expiraciones largas (15 min+), a horas fijas
#   digital -> opciones digitales con strike, payout variable
BINARY_KINDS = ("turbo", "binary")


def is_otc(name: str) -> bool:
    return "-OTC" in name.upper() or name.upper().endswith("_OTC")


def main() -> int:
    ap = argparse.ArgumentParser(description="Diagnostico de activos abiertos en el broker")
    ap.add_argument("--real-only", action="store_true",
                    help="Mostrar solo activos de mercado real (sin OTC)")
    ap.add_argument("--min-payout", type=float, default=0.0,
                    help="Filtrar activos por payout minimo, ej 0.80")
    args = ap.parse_args()

    from dotenv import load_dotenv
    load_dotenv()

    email = os.getenv("EXNOVA_EMAIL", "")
    password = os.getenv("EXNOVA_PASSWORD", "")
    if not email or not password:
        print("ERROR: define EXNOVA_EMAIL y EXNOVA_PASSWORD en .env o en el entorno")
        return 1

    from exnovaapi.stable_api import Exnova

    # Diagnostico de solo lectura: siempre en PRACTICE, nunca toca saldo real.
    api = Exnova(email, password)
    ok, reason = api.connect()
    if not ok:
        print(f"ERROR de conexion: {reason}")
        return 1
    api.change_balance("PRACTICE")

    now_utc = datetime.now(timezone.utc)
    print("=" * 78)
    print("ACTIVOS ABIERTOS SEGUN EL BROKER")
    print("=" * 78)
    print(f"Hora UTC        : {now_utc:%Y-%m-%d %H:%M} ({now_utc:%A})")
    print(f"Cuenta          : PRACTICE (diagnostico de solo lectura)")
    print(f"Balance demo    : {api.get_balance()}")

    # Fin de semana: el mercado real de forex esta cerrado y SOLO existe OTC.
    # Esta es la causa mas frecuente de "solo me deja operar sinteticos".
    weekday = now_utc.weekday()  # 0=lunes ... 6=domingo
    if weekday >= 5:
        print("\n>>> AVISO: es fin de semana en UTC. El mercado real de forex esta")
        print(">>> cerrado, por lo que el broker SOLO ofrece activos -OTC sinteticos.")
        print(">>> Para operar mercado real hay que hacerlo de lunes a viernes.")

    # No usamos api.get_all_open_time(): lanza tres hilos y dos de ellos
    # (digital y cfd/forex/crypto) se cuelgan indefinidamente contra este
    # broker. Leemos directamente la fuente de turbo/binary, que es la unica
    # que importa para opciones binarias.
    print("\nConsultando turbo/binary via get_all_init_v2()...")
    try:
        init = api.get_all_init_v2()
    except Exception as e:
        print(f"ERROR al consultar activos: {e}")
        return 1

    open_time: dict[str, dict[str, dict]] = {}
    for kind in ("turbo", "binary"):
        bucket: dict[str, dict] = {}
        for active in (init.get(kind, {}).get("actives", {}) or {}).values():
            raw = str(active.get("name", ""))
            name = raw.split(".")[1] if "." in raw else raw
            enabled = active.get("enabled", False)
            is_open = bool(enabled) and not active.get("is_suspended", False)
            bucket[name] = {"open": is_open}
        open_time[kind] = bucket

    try:
        profits = api.get_all_profit()
    except Exception:
        profits = {}

    def payout_of(asset: str, kind: str) -> float | None:
        entry = profits.get(asset)
        if not isinstance(entry, dict):
            return None
        val = entry.get(kind)
        return float(val) if isinstance(val, (int, float)) else None

    grand_total = {"real": 0, "otc": 0}

    for kind in BINARY_KINDS:
        assets = open_time.get(kind, {})
        opened = sorted(a for a, v in assets.items() if v.get("open"))

        reals = [a for a in opened if not is_otc(a)]
        otcs = [a for a in opened if is_otc(a)]
        grand_total["real"] += len(reals)
        grand_total["otc"] += len(otcs)

        print("\n" + "-" * 78)
        print(f"{kind.upper()}  ->  {len(opened)} abiertos "
              f"({len(reals)} de mercado real, {len(otcs)} sinteticos OTC)")
        print("-" * 78)

        groups = [("MERCADO REAL", reals)]
        if not args.real_only:
            groups.append(("SINTETICOS OTC", otcs))

        for title, names in groups:
            if not names:
                print(f"  {title}: ninguno abierto ahora")
                continue
            print(f"  {title}:")
            shown = 0
            for a in names:
                p = payout_of(a, kind)
                if p is not None and p < args.min_payout:
                    continue
                # Payout 0.84 significa: ganas 84 centavos por cada dolar arriesgado.
                if p is None:
                    ptxt = "payout n/d"
                else:
                    ptxt = f"payout {p:.2f} -> break-even {100 / (1 + p):.1f}%"
                print(f"    {a:<22} {ptxt}")
                shown += 1
            if shown == 0:
                print(f"    (ninguno supera el payout minimo {args.min_payout})")

    print("\n" + "=" * 78)
    print(f"TOTAL: {grand_total['real']} activos de mercado real, "
          f"{grand_total['otc']} sinteticos OTC")
    print("=" * 78)
    if grand_total["real"] == 0:
        print("No hay NINGUN activo de mercado real abierto en este momento.")
        print("Causas posibles, por orden de frecuencia:")
        print("  1. Es fin de semana o fuera del horario del mercado subyacente.")
        print("  2. La cuenta/region no tiene habilitados esos instrumentos.")
        print("  3. El broker no los ofrece como opcion binaria, solo como CFD.")
    else:
        print("Hay mercado real disponible: el bot deberia priorizarlo sobre OTC.")
        print("Nota: el bot actual NUNCA llama a get_all_open_time(); opera desde")
        print("la lista fija de bot/config_assets.py, que es por lo que solo ves OTC.")

    try:
        api.close_connect()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
