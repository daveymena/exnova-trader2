"""
Backfill: Puebla SupervisedZoneLearner con 292 trades historicos.
- Sin entry_price real -> agrupa por (asset, direction) con nivel sintetico unico
- Cada grupo = 1 zona con wins/losses acumulados
- Asi get_opportunity() ve zonas con >=3 analisis y WR real
"""
import json
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from brain.supervised_zone_learner import SupervisedZoneLearner

HISTORY_PATH = os.path.join(os.path.dirname(__file__), "trade_history.json")


def backfill():
    with open(HISTORY_PATH, "r") as f:
        data = json.load(f)
    trades = data.get("trades", [])
    print(f"Cargados {len(trades)} trades historicos")

    zl = SupervisedZoneLearner()

    # Agrupar por (asset, direction)
    groups = {}
    for t in trades:
        key = (t["asset"], t["direction"])
        groups.setdefault(key, []).append(t)

    print(f"Agrupados en {len(groups)} zonas (asset x direction)")

    syn_level = 1.0
    for (asset, direction), group in sorted(groups.items()):
        wins = sum(1 for t in group if t["result"] == "WIN")
        losses = sum(1 for t in group if t["result"] == "LOSS")
        wr = wins / (wins + losses) * 100 if (wins + losses) > 0 else 0
        print(f"  {asset} {direction}: {wins}W/{losses}L = {wr:.0f}%")

        for t in group:
            zl.record_trade_result(
                asset=asset,
                direction=direction,
                entry=syn_level,
                exit=syn_level,
                result=t["result"],
                level=syn_level,
            )

        # Level unico por zona
        syn_level += 0.001

    zl.save()

    s = zl.summary()
    print(f"\nBackfill completo:")
    print(f"  Zonas creadas: {s['total_zonas']}")
    print(f"  Zonas con analisis: {s['zonas_con_analisis']}")
    print(f"  Listas para practice: {s['listas_para_practice']}")
    print(f"  Analisis completados: {s['analisis_completados']}")
    print(f"  Win rate real: {s['win_rate_real']:.1f}%")

    # Mostrar zonas listas
    ready = []
    for asset, zones in zl.zones.items():
        for z in zones:
            if z.completed_analyses >= 3 and z.analysis_win_rate >= 0.55 and z.strength >= 0.50:
                ready.append((asset, z.zone_type, z.completed_analyses, z.analysis_win_rate*100))

    if ready:
        print(f"\nZonas listas ({len(ready)}):")
        for asset, ztype, n, wr in ready:
            print(f"  {asset} {ztype}: {n} analisis, WR={wr:.0f}%")
    else:
        print("\nNinguna zona cumple los requisitos minimos aun")


if __name__ == "__main__":
    backfill()
