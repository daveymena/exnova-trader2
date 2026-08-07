"""
Market Structure Engine — arma el mapa que un trader discrecional
construiría a mano al mirar el gráfico: sesgo macro (H1/M15, D1 si hay)
y en qué etapa de un retroceso está el precio en M15 y en el timeframe
mayor (M30/H1), para decidir si conviene entrar en la reanudación de la
tendencia tras un pullback, esperar, o dejar pasar sin opinión.

Solo tiene sentido usarlo con activos reales (no-OTC): ver
bot/core/asset_discovery.is_otc. En OTC el precio es un paseo aleatorio
medido, así que este motor no se invoca ahí.
"""
from typing import Dict, Optional

import pandas as pd

from brain.macro_trend_analyzer import MacroTrendAnalyzer
from brain.retracement_timing import RetracementTimingAnalyzer


class MarketStructureEngine:

    def __init__(self):
        self.macro_analyzer = MacroTrendAnalyzer()
        self.retracement_analyzer = RetracementTimingAnalyzer()

    def build_map(self, asset: str, df_m1: pd.DataFrame, df_m5: pd.DataFrame,
                  df_m15: pd.DataFrame, df_htf: Optional[pd.DataFrame],
                  htf_minutes: int, context: Dict) -> Dict:
        """
        context: el dict que ya devuelve ContextAnalyzer.analyze() en
        evaluate_market() — se reutiliza structure_m15/structure_h1 en vez
        de recalcular pivots.
        """
        momentum = context.get("momentum", {})
        rsi_by_tf = {"m1": momentum.get("rsi_m1", 50.0), "m5": momentum.get("rsi_m5", 50.0)}
        precomputed = {}
        for tf_key, ctx_key in (("m1", "structure_m1"), ("m5", "structure_m5"),
                                 ("m15", "structure_m15"), ("h1", "structure_h1")):
            ctx_structure = context.get(ctx_key)
            if ctx_structure:
                precomputed[tf_key] = self._adapt_structure(ctx_structure, rsi=rsi_by_tf.get(tf_key, 50.0))

        macro = self.macro_analyzer.analyze_macro_context(
            df_m1=df_m1, df_m5=df_m5, df_m15=df_m15, df_h1=df_htf, df_d1=None,
            precomputed_structures=precomputed,
        )

        retracement_m15 = self.retracement_analyzer.analyze(
            df_m15, context.get("structure_m15"), timeframe_minutes=15,
        )
        if df_htf is not None:
            retracement_htf = self.retracement_analyzer.analyze(
                df_htf, context.get("structure_h1"), timeframe_minutes=htf_minutes,
            )
        else:
            retracement_htf = self.retracement_analyzer._empty("sin timeframe mayor disponible")

        entry_bias, reason = self._combine(macro, retracement_m15, retracement_htf)

        return {
            "asset": asset,
            "macro_trend": macro["macro_trend"],
            "macro_trap_risk": macro["trap_risk"],
            "macro_reason": macro["reason"],
            "retracement_m15": retracement_m15,
            "retracement_htf": retracement_htf,
            "entry_bias": entry_bias,
            "reason": reason,
        }

    @staticmethod
    def _adapt_structure(ctx_structure: Dict, rsi: float = 50.0) -> Dict:
        """
        Traduce el dict de ContextAnalyzer._market_structure (pivots
        confirmados: trend uptrend/downtrend/neutral/volatile) al formato
        que espera MacroTrendAnalyzer (trend up/down/neutral + strength),
        para que use esta estructura robusta en vez de su propio detector
        de "últimas 3 velas", que confunde un retroceso con una reversión.
        """
        trend = ctx_structure.get("trend", "neutral")
        hh = trend == "uptrend"
        ll = trend == "downtrend"
        hl = bool(ctx_structure.get("hl"))
        lh = bool(ctx_structure.get("lh"))
        confirmed_up = hh and hl
        confirmed_down = ll and lh
        strength = 0.8 if (confirmed_up or confirmed_down) else 0.4
        return {
            "trend": "up" if hh else "down" if ll else "neutral",
            "structure": ctx_structure.get("structure", "unclear"),
            "strength": strength,
            "hh": hh, "ll": ll, "hl": hl, "lh": lh,
            "rsi": rsi,
            "atr": 0.0,
            "recent_high": ctx_structure.get("swing_high", 0.0),
            "recent_low": ctx_structure.get("swing_low", 0.0),
            "recent_close": 0.0,
        }

    def _combine(self, macro: Dict, ret_m15: Dict, ret_htf: Dict):
        """
        Devuelve (entry_bias, reason):
        - "WAIT": rechazar la entrada propuesta pase lo que pase.
        - "CALL"/"PUT": el timing de retroceso confirma y refuerza esa dirección.
        - "NEUTRAL": este motor no tiene opinión — dejar la decisión al resto
          del pipeline (caso de continuación pura de tendencia sin pullback).
        """
        macro_up = macro["macro_trend"] in ("strong_up", "weak_up")
        macro_down = macro["macro_trend"] in ("strong_down", "weak_down")

        if ret_m15["stage"] == "invalidated" or ret_htf["stage"] == "invalidated":
            return "WAIT", "Retroceso invalidó la estructura previa (rompió el swing anterior) — posible reversión, no continuación"

        if macro["trap_risk"] >= 0.65:
            return "WAIT", f"Riesgo alto de trampa macro ({macro['trap_risk']:.2f}): {macro['reason']}"

        if ret_m15["stage"] == "mature" and ret_m15["expected_direction"] != "NEUTRAL":
            aligned_with_macro = (
                (ret_m15["expected_direction"] == "CALL" and not macro_down) or
                (ret_m15["expected_direction"] == "PUT" and not macro_up)
            )
            # No basta con que el score macro no contradiga: el timeframe mayor
            # (M30/H1) debe tener SU PROPIA estructura de swings confirmando la
            # misma dirección que M15. Justo en un giro, un rebote local puede
            # verse "alcista" en M15 mientras el resto sigue siendo una tendencia
            # bajista mayor — sin esta confirmación independiente, ese rebote se
            # confunde con una reanudación de tendencia real.
            htf_confirms = ret_htf["direction"] == ret_m15["direction"]
            if aligned_with_macro and htf_confirms:
                return ret_m15["expected_direction"], (
                    f"Retroceso M15 maduro ({ret_m15['candles_elapsed']} velas, "
                    f"{ret_m15['retracement_depth_pct']:.0%} de profundidad) alineado con macro "
                    f"{macro['macro_trend']} y con estructura del timeframe mayor "
                    f"({ret_htf['direction']}) — probable reanudación de tendencia"
                )
            if aligned_with_macro and not htf_confirms:
                return "NEUTRAL", (
                    f"Retroceso M15 parece maduro pero el timeframe mayor no confirma la misma "
                    f"dirección (m15={ret_m15['direction']}, htf={ret_htf['direction']}) — "
                    "posible rebote dentro de una tendencia mayor opuesta, no continuación real"
                )

        if ret_m15["stage"] == "developing":
            return "WAIT", "Retroceso M15 aún desarrollándose — esperar a que madure antes de entrar"

        return "NEUTRAL", "Sin señal de retroceso relevante para este ciclo"
