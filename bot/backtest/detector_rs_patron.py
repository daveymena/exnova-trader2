"""
detector_rs.py - Detector del patrón "Retroceso a favor" (estilo de entrada de Duvier) - v1.0

Qué hace:
  - Recibe velas OHLC (de 10 s, 15 s o 1 min) y detecta, vela por vela, las entradas que
    cumplen el patrón documentado en "patron_entrada_y_momentum.md".
  - Incluye un backtest simple de opciones binarias/Blitz para medir el patrón con datos reales.

Qué NO hace:
  - No se conecta a IQ Option ni abre operaciones. La ejecución va en otro módulo y debe
    probarse primero en la cuenta de PRÁCTICA.

Uso rápido (CSV con columnas: time,open,high,low,close):
  python detector_rs.py velas.csv --vencimiento 18 --payout 0.85
"""
from __future__ import annotations

import csv
import sys
from dataclasses import dataclass, asdict
from typing import List, Optional, Dict


# ----------------------------------------------------------------------------- parámetros
@dataclass
class Params:
    # Indicadores (los mismos del Edge Scanner de Duvier: EMA 20/50/200 sobre el cierre)
    ema_rapida: int = 20
    ema_media: int = 50
    ema_lenta: int = 200
    atr_periodo: int = 14
    # Tendencia
    pendiente_velas: int = 5            # velas para medir la pendiente de la EMA20
    pendiente_min_atr: float = 0.03     # pendiente mínima de EMA20 por vela, en unidades de ATR
    swing_k: int = 2                    # un swing es el extremo de 2 velas a cada lado
    # Impulso y retroceso (momentum)
    impulso_ventana: int = 10           # velas hacia atrás donde se busca el inicio del impulso
    impulso_min_atr: float = 1.2        # el impulso debe medir al menos 1.2 ATR
    retroceso_min_velas: int = 1
    retroceso_max_velas: int = 6
    retroceso_min_pct: float = 0.20     # el retroceso corrige entre el 20 % ...
    retroceso_max_pct: float = 0.75     # ... y el 75 % del impulso
    retroceso_cuerpo_max: float = 0.85  # cuerpo medio del retroceso <= 85 % del cuerpo medio del impulso
    # Lugar exacto
    toque_ema_atr: float = 0.35         # el retroceso debe llegar a <= 0.35 ATR de la EMA20
    dist_max_ema20_atr: float = 1.0     # al disparar, el cierre está a <= 1 ATR de la EMA20
    rango_velas: int = 30               # ventana del rango reciente (30 velas de 10 s = 5 min)
    zona_alta: float = 0.66             # setup C: techo del rango
    zona_baja: float = 0.33             # setup C: piso del rango
    zona_extrema_call: float = 0.85     # A/B: no comprar con el cierre en el 15 % más alto del rango
    zona_extrema_put: float = 0.15      # A/B: no vender con el cierre en el 15 % más bajo del rango
    # Filtros
    vela_grande_factor: float = 2.0     # F2: vela >= 2x el cuerpo medio de las últimas 10
    extension_max_atr: float = 2.0      # F1/F2: precio a más de 2 ATR de la EMA20 = movimiento agotado
    rango_min_atr: float = 2.0          # F7: rango de la ventana < 2 ATR = lateral estrecho
    cruce_reciente_velas: int = 10      # F7: si EMA20 y EMA50 se cruzaron en las últimas 10 velas, no operar
    # Setup C (piso/techo de rango con EMAs planas)
    toques_min: int = 2
    toque_tol_pct: float = 0.10         # tolerancia del toque = 10 % del ancho del rango
    mecha_factor: float = 1.5
    # Operativa (backtest y bot)
    vencimiento_velas: int = 18         # 18 velas de 10 s = 3 min (con velas de 1 min usar 3)
    enfriamiento_velas: int = 6         # F5: velas de espera después de cada vencimiento
    bloqueo_giro_velas: int = 12        # no cambiar de dirección tras una pérdida durante N velas
    payout: float = 0.85


# ----------------------------------------------------------------------------- indicadores
def ema(valores: List[float], periodo: int) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(valores)
    if len(valores) < periodo:
        return out
    k = 2.0 / (periodo + 1)
    sma = sum(valores[:periodo]) / periodo
    out[periodo - 1] = sma
    prev = sma
    for i in range(periodo, len(valores)):
        prev = valores[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def atr(velas: List[Dict], periodo: int) -> List[Optional[float]]:
    tr = []
    for i, v in enumerate(velas):
        if i == 0:
            tr.append(v["h"] - v["l"])
        else:
            pc = velas[i - 1]["c"]
            tr.append(max(v["h"] - v["l"], abs(v["h"] - pc), abs(v["l"] - pc)))
    out: List[Optional[float]] = [None] * len(velas)
    if len(velas) < periodo:
        return out
    a = sum(tr[:periodo]) / periodo
    out[periodo - 1] = a
    for i in range(periodo, len(velas)):
        a = (a * (periodo - 1) + tr[i]) / periodo
        out[i] = a
    return out


def swings(velas: List[Dict], k: int, hasta: int):
    """Swings confirmados (necesitan k velas a la derecha) con índice < hasta."""
    altos, bajos = [], []
    for i in range(k, hasta - k):
        h, l = velas[i]["h"], velas[i]["l"]
        if all(h > velas[j]["h"] for j in range(i - k, i)) and all(h >= velas[j]["h"] for j in range(i + 1, i + k + 1)):
            altos.append(i)
        if all(l < velas[j]["l"] for j in range(i - k, i)) and all(l <= velas[j]["l"] for j in range(i + 1, i + k + 1)):
            bajos.append(i)
    return altos, bajos


def cuerpo(v: Dict) -> float:
    return abs(v["c"] - v["o"])


# ----------------------------------------------------------------------------- detector
class Detector:
    def __init__(self, velas: List[Dict], p: Params = Params()):
        self.v = velas
        self.p = p
        cierres = [x["c"] for x in velas]
        self.e20 = ema(cierres, p.ema_rapida)
        self.e50 = ema(cierres, p.ema_media)
        self.e200 = ema(cierres, p.ema_lenta)
        self.atr = atr(velas, p.atr_periodo)

    # --- utilidades
    def _listo(self, i: int) -> bool:
        p = self.p
        return i >= max(p.ema_lenta, p.rango_velas, p.impulso_ventana + p.retroceso_max_velas + 2) + p.pendiente_velas \
            and self.e200[i] is not None and self.atr[i]

    def _pos_rango(self, i: int):
        w = self.v[i - self.p.rango_velas + 1:i + 1]
        hi, lo = max(x["h"] for x in w), min(x["l"] for x in w)
        pos = (self.v[i]["c"] - lo) / (hi - lo) if hi > lo else 0.5
        return pos, hi, lo

    def _cruce_reciente(self, i: int) -> bool:
        n = self.p.cruce_reciente_velas
        signos = [(self.e20[j] - self.e50[j]) > 0 for j in range(i - n, i + 1)]
        return any(signos[j] != signos[j - 1] for j in range(1, len(signos)))

    def _tendencia(self, i: int) -> str:
        p, a = self.p, self.atr[i]
        pend = (self.e20[i] - self.e20[i - p.pendiente_velas]) / (p.pendiente_velas * a)
        if self.e20[i] > self.e50[i] > self.e200[i] and pend >= p.pendiente_min_atr:
            return "ALCISTA"
        if self.e20[i] < self.e50[i] < self.e200[i] and pend <= -p.pendiente_min_atr:
            return "BAJISTA"
        if abs(pend) < p.pendiente_min_atr:
            return "PLANA"
        return "MIXTA"

    def _estructura_ok(self, i: int, direccion: str) -> bool:
        altos, bajos = swings(self.v, self.p.swing_k, i)
        if direccion == "CALL":
            if len(bajos) < 2:
                return False
            return self.v[bajos[-1]]["l"] > self.v[bajos[-2]]["l"]   # mínimos crecientes
        if len(altos) < 2:
            return False
        return self.v[altos[-1]]["h"] < self.v[altos[-2]]["h"]       # máximos decrecientes

    # --- setups A / B (retroceso a favor de la tendencia)
    def _retroceso(self, i: int, direccion: str):
        p, v, a = self.p, self.v, self.atr[i]
        ini = i - p.retroceso_max_velas - 1
        ventana = range(ini, i)
        if direccion == "CALL":
            j = max(ventana, key=lambda x: v[x]["h"])                     # techo del impulso
            m = min(range(j - p.impulso_ventana, j + 1), key=lambda x: v[x]["l"])
            pierna = v[j]["h"] - v[m]["l"]
            extremo_ret = min(v[x]["l"] for x in range(j + 1, i + 1)) if j + 1 <= i else v[i]["l"]
            prof = (v[j]["h"] - extremo_ret) / pierna if pierna > 0 else 0
            toca_ema = extremo_ret <= self.e20[i] + p.toque_ema_atr * a
            sobre_e50 = all(v[x]["c"] >= self.e50[x] for x in range(j + 1, i + 1))
        else:
            j = min(ventana, key=lambda x: v[x]["l"])
            m = max(range(j - p.impulso_ventana, j + 1), key=lambda x: v[x]["h"])
            pierna = v[m]["h"] - v[j]["l"]
            extremo_ret = max(v[x]["h"] for x in range(j + 1, i + 1)) if j + 1 <= i else v[i]["h"]
            prof = (extremo_ret - v[j]["l"]) / pierna if pierna > 0 else 0
            toca_ema = extremo_ret >= self.e20[i] - p.toque_ema_atr * a
            sobre_e50 = all(v[x]["c"] <= self.e50[x] for x in range(j + 1, i + 1))
        n_ret = i - j - 1                                                  # velas de retroceso antes del gatillo
        imp = [cuerpo(v[x]) for x in range(min(m, j), max(m, j) + 1)]
        ret = [cuerpo(v[x]) for x in range(j + 1, i)] or [0.0]
        perdida_fuerza = (sum(ret) / len(ret)) <= p.retroceso_cuerpo_max * (sum(imp) / len(imp)) if imp else False
        checks = {
            "impulso>=min": pierna >= p.impulso_min_atr * a,
            "velas_retroceso_ok": p.retroceso_min_velas <= n_ret <= p.retroceso_max_velas,
            "profundidad_ok": p.retroceso_min_pct <= prof <= p.retroceso_max_pct,
            "retroceso_pierde_fuerza": perdida_fuerza,
            "toca_zona_EMA20": toca_ema,
            "no_cierra_tras_EMA50": sobre_e50,
        }
        return checks, dict(impulso_atr=round(pierna / a, 2), profundidad=round(prof, 2), velas_retroceso=n_ret)

    def _gatillo(self, i: int, direccion: str) -> bool:
        v = self.v
        if direccion == "CALL":
            return v[i]["c"] > v[i]["o"] and v[i]["c"] > v[i - 1]["h"]
        return v[i]["c"] < v[i]["o"] and v[i]["c"] < v[i - 1]["l"]

    def _filtros(self, i: int, direccion: str, pos: float, rango: float) -> Dict[str, bool]:
        """Devuelve los filtros que BLOQUEAN la entrada (True = bloquea)."""
        p, v, a = self.p, self.v, self.atr[i]
        cuerpos10 = [cuerpo(v[x]) for x in range(i - 10, i)]
        vela_grande = cuerpo(v[i]) >= p.vela_grande_factor * (sum(cuerpos10) / 10)
        dist = (v[i]["c"] - self.e20[i]) / a
        if direccion == "CALL":
            f1 = dist < -p.extension_max_atr                 # comprar con el precio hundido (vender ya pasó)
            f2 = (vela_grande and pos >= p.zona_alta) or dist > p.extension_max_atr
            zona_mala = pos > p.zona_extrema_call
        else:
            f1 = dist > p.extension_max_atr
            f2 = (vela_grande and pos <= p.zona_baja) or dist < -p.extension_max_atr
            zona_mala = pos < p.zona_extrema_put
        return {
            "F1_movimiento_ya_hecho": f1 or zona_mala,
            "F2_vela_impulso/extendido": f2,
            "F7_lateral_estrecho": rango < p.rango_min_atr * a,
            "F7_cruce_EMAs_reciente": self._cruce_reciente(i),
            "lejos_de_EMA20": abs(dist) > p.dist_max_ema20_atr,
        }

    # --- setup C (piso / techo de rango con EMAs planas)
    def _setup_c(self, i: int, pos: float, hi: float, lo: float):
        p, v, a = self.p, self.v, self.atr[i]
        ancho = hi - lo
        if ancho < p.rango_min_atr * a:
            return None
        w = range(i - p.rango_velas + 1, i)
        tol = p.toque_tol_pct * ancho
        toques_piso = sum(1 for x in w if v[x]["l"] <= lo + tol)
        toques_techo = sum(1 for x in w if v[x]["h"] >= hi - tol)
        c = v[i]
        mecha_inf = min(c["o"], c["c"]) - c["l"]
        mecha_sup = c["h"] - max(c["o"], c["c"])
        if pos <= p.zona_baja and toques_piso >= p.toques_min and (
                mecha_inf >= p.mecha_factor * max(cuerpo(c), 1e-12) or self._gatillo(i, "CALL")):
            return "CALL", "C_CALL_piso_rango", dict(toques=toques_piso, pos=round(pos, 2))
        if pos >= p.zona_alta and toques_techo >= p.toques_min and (
                mecha_sup >= p.mecha_factor * max(cuerpo(c), 1e-12) or self._gatillo(i, "PUT")):
            return "PUT", "A_PUT_techo_rango", dict(toques=toques_techo, pos=round(pos, 2))
        return None

    # --- API principal
    def senal(self, i: int) -> Optional[Dict]:
        """Evalúa la vela i ya CERRADA. Si hay señal, la entrada es en la apertura de la vela i+1."""
        if not self._listo(i):
            return None
        tend = self._tendencia(i)
        pos, hi, lo = self._pos_rango(i)
        rango = hi - lo
        if tend in ("ALCISTA", "BAJISTA"):
            d = "CALL" if tend == "ALCISTA" else "PUT"
            if not self._gatillo(i, d) or not self._estructura_ok(i, d):
                return None
            checks, info = self._retroceso(i, d)
            if not all(checks.values()):
                return None
            bloqueos = self._filtros(i, d, pos, rango)
            if any(bloqueos.values()):
                return None
            setup = "B_CALL_retroceso_EMA" if d == "CALL" else "A_PUT_retroceso_EMA"
            return dict(indice=i, entrada_en=i + 1, direccion=d, setup=setup, tendencia=tend,
                        pos_rango=round(pos, 2), **info)
        if tend == "PLANA":
            r = self._setup_c(i, pos, hi, lo)
            if r:
                d, setup, info = r
                return dict(indice=i, entrada_en=i + 1, direccion=d, setup=setup, tendencia=tend, **info)
        return None


# ----------------------------------------------------------------------------- backtest
def backtest(velas: List[Dict], p: Params = Params()) -> Dict:
    det = Detector(velas, p)
    ops = []
    libre_desde = 0
    ultimo_perdido = None  # (direccion, indice_vencimiento)
    for i in range(len(velas) - p.vencimiento_velas - 1):
        if i < libre_desde:
            continue
        s = det.senal(i)
        if not s:
            continue
        if ultimo_perdido and s["direccion"] != ultimo_perdido[0] and i - ultimo_perdido[1] < p.bloqueo_giro_velas:
            continue  # no girar de dirección justo después de perder
        e = i + 1
        venc = e + p.vencimiento_velas - 1
        entrada = velas[e]["o"]
        salida = velas[venc]["c"]
        if salida == entrada:
            res, pg = "EMPATE", 0.0
        elif (salida > entrada) == (s["direccion"] == "CALL"):
            res, pg = "GANADA", p.payout
        else:
            res, pg = "PERDIDA", -1.0
        ops.append(dict(s, entrada=entrada, salida=salida, resultado=res, pg_por_1usd=pg,
                        t_entrada=velas[e].get("t"), t_venc=velas[venc].get("t")))
        libre_desde = venc + 1 + p.enfriamiento_velas
        ultimo_perdido = (s["direccion"], venc) if res == "PERDIDA" else None
    g = sum(o["resultado"] == "GANADA" for o in ops)
    l = sum(o["resultado"] == "PERDIDA" for o in ops)
    return dict(operaciones=ops, n=len(ops), ganadas=g, perdidas=l,
                acierto=round(100 * g / (g + l), 1) if g + l else None,
                pg_por_1usd=round(sum(o["pg_por_1usd"] for o in ops), 2),
                break_even=round(100 / (1 + p.payout), 1))


# ----------------------------------------------------------------------------- CLI
def cargar_csv(ruta: str) -> List[Dict]:
    out = []
    with open(ruta, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            out.append(dict(t=r.get("time") or r.get("t"), o=float(r["open"]), h=float(r["high"]),
                            l=float(r["low"]), c=float(r["close"])))
    return out


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Backtest del patrón Retroceso a favor")
    ap.add_argument("csv")
    ap.add_argument("--vencimiento", type=int, default=18, help="velas hasta el vencimiento")
    ap.add_argument("--rango", type=int, default=30, help="velas de la ventana de rango")
    ap.add_argument("--payout", type=float, default=0.85)
    a = ap.parse_args()
    prm = Params(vencimiento_velas=a.vencimiento, rango_velas=a.rango, payout=a.payout)
    r = backtest(cargar_csv(a.csv), prm)
    print({k: v for k, v in r.items() if k != "operaciones"})
    for o in r["operaciones"][:50]:
        print(o)
