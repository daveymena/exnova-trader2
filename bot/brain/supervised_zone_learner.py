# -*- coding: utf-8 -*-
"""
Supervised Zone Learner - Aprendizaje con resultados REALES del mercado

NO opera en segundo plano.
NO simula velas hacia adelante.

Flujo real:
1. Observa M1+M15, detecta swings con rechazo (entrada potencial)
2. Encola la entrada como "pendiente de resultado"
3. Cada ciclo revisa si expiro el tiempo de la entrada
4. Cuando expira, consulta el precio REAL de la API
5. Guarda: ?se gano o perdio? junto con contexto M15 completo
6. Acumula conocimiento: zonas + condiciones donde el mercado realmente gana
7. Cuando hay suficiente evidencia, permite operar en MODO PRACTICE (demo)
"""
import json
import os
import time
from dataclasses import asdict, dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

import pandas as pd
import numpy as np

# ─── CONSTANTES ────────────────────────────────────────────────────────────

MIN_WICK_RATIO = 0.5
MIN_REACTION_PIPS = 3
SWING_WINDOW_M1 = 5
# El motor live ejecuta con un piso de 180s. Medir otros horizontes como si
# fueran entradas independientes triplica las muestras del mismo evento.
EXPIRATIONS = [180]
# Muestras independientes mínimas antes de confiar en una zona.
MIN_ZONE_ANALYSES = 20
PRACTICE_BALANCE = 1000.0       # balance inicial para modo demo


@dataclass
class PendingAnalysis:
    """Entrada pendiente de resultado real."""
    id: str
    asset: str
    entry_time: float
    entry_price: float
    direction: str               # CALL / PUT
    zone_type: str               # support / resistance
    zone_level: float
    expiration_sec: int          # 60, 120, 300
    m15_trend: str = "neutral"
    m15_phase: str = "unknown"
    m15_rsi: float = 50.0
    m15_structure: str = "unknown"
    m15_trend_aligned: bool = False
    m1_rejection_pips: float = 0.0
    m1_rsi: float = 50.0
    resolved: bool = False
    result: str = "PENDING"      # WIN / LOSS / PENDING
    exit_price: float = 0.0
    pips: float = 0.0
    resolved_ts: float = 0.0
    why_entry: str = ""


@dataclass
class CompletedAnalysis:
    asset: str
    entry_time: float
    entry_price: float
    direction: str
    zone_type: str
    expiration_sec: int
    result: str
    pips: float
    max_fav_pips: float
    max_adv_pips: float
    m15_trend: str
    m15_phase: str
    m15_rsi: float
    m15_structure: str
    m15_trend_aligned: bool
    m1_rejection_pips: float
    m1_rsi: float
    why_entry: str
    lesson: str


@dataclass
class ObservedZone:
    asset: str
    level: float
    zone_type: str
    touches: int = 0
    holds: int = 0
    breaks: int = 0
    last_touch_ts: float = 0.0
    first_seen_ts: float = 0.0
    avg_reaction_pips: float = 0.0
    completed_analyses: int = 0
    analysis_wins: int = 0
    analysis_losses: int = 0
    avg_m15_aligned: float = 0.0
    avg_overshoot_fav: float = 0.0
    avg_overshoot_adv: float = 0.0

    @property
    def analysis_win_rate(self) -> float:
        total = self.analysis_wins + self.analysis_losses
        if total == 0:
            return 0.0
        return self.analysis_wins / total

    @property
    def analysis_lower_bound(self) -> float:
        """Límite inferior Wilson 95% para no operar WR inflado por ruido."""
        n = self.analysis_wins + self.analysis_losses
        if n == 0:
            return 0.0
        z = 1.96
        p = self.analysis_wins / n
        denominator = 1 + z * z / n
        center = (p + z * z / (2 * n)) / denominator
        margin = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
        return max(0.0, center - margin)

    @property
    def strength(self) -> float:
        touch_score = min(self.touches / 10.0, 1.0)
        hold_score = self.holds / self.touches if self.touches > 0 else 0
        age_hours = (time.time() - self.last_touch_ts) / 3600 if self.last_touch_ts > 0 else 48
        recency_score = max(0.0, 1.0 - age_hours / 72.0)
        pip_score = min(self.avg_reaction_pips / 25.0, 1.0) if self.avg_reaction_pips > 0 else 0.2
        analysis_score = self.analysis_win_rate * 0.5 if self.analysis_win_rate > 0 else 0.0
        trend_score = self.avg_m15_aligned

        return (
            hold_score * 0.25
            + touch_score * 0.15
            + recency_score * 0.10
            + pip_score * 0.05
            + analysis_score * 0.30
            + trend_score * 0.15
        )


class SupervisedZoneLearner:
    """
    Observa mercado real, encola entradas, espera expiracion real,
    registra resultados reales y construye conocimiento.
    """

    def __init__(
        self,
        persist_path: str = "brain/supervised_zone_learning.json",
        analysis_path: str = "brain/market_analysis_history.json",
        pending_path: str = "brain/pending_analyses.json",
        get_current_price_fn: Optional[Callable] = None,
    ):
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.persist_path = os.path.join(base_dir, "..", persist_path)
        self.analysis_path = os.path.join(base_dir, "..", analysis_path)
        self.pending_path = os.path.join(base_dir, "..", pending_path)
        self.get_current_price = get_current_price_fn
        self.zones: Dict[str, List[ObservedZone]] = {}
        self.pending: List[Dict] = []
        self.completed: List[Dict] = []
        self._loaded_ts: Dict[str, float] = {}
        self._load()

    # ═══════════════════════════════════════════════════════════════
    #  API PUBLICA
    # ═══════════════════════════════════════════════════════════════

    def observe(self, asset: str, df_m1: pd.DataFrame, df_m15: Optional[pd.DataFrame] = None) -> int:
        """
        Cada ciclo:
        1. Resuelve entradas pendientes que ya expiraron
        2. Detecta nuevos swings como entradas potenciales
        3. Las encola para resolver en el futuro
        """
        if df_m1 is None or df_m1.empty or len(df_m1) < 15:
            return 0

        now = time.time()

        # 1. Resolver pendientes expirados
        resueltos = self._resolve_pending(asset, df_m1)
        self._save_analyses()

        # 2. Limitar frecuencia de nuevos analisis (60s por activo)
        last_ts = self._loaded_ts.get(asset, 0.0)
        newest_ts = df_m1.index[-1].timestamp() if hasattr(df_m1.index[-1], "timestamp") else now
        if newest_ts - last_ts < 60:
            return resueltos
        self._loaded_ts[asset] = newest_ts

        # 3. Detectar nuevos swings
        swings = self._detect_swings(df_m1)
        if not swings:
            return resueltos

        latest = swings[-1]
        zone_type = latest["type"]
        direction = "CALL" if zone_type == "support" else "PUT"
        level = latest["level"]
        idx = latest["idx"]
        # Usar el close real de la vela swing como precio de entrada realista
        if idx < len(df_m1):
            entry_price = float(df_m1["close"].iloc[idx])
        else:
            entry_price = level
        reaction_pips = abs(latest.get("reaction_pips", 0))
        rsi_val = self._calc_rsi(df_m1, idx)

        if reaction_pips < MIN_REACTION_PIPS:
            return resueltos

        # No duplicar: verificar que no haya un pending similar reciente
        if self._has_recent_pending(asset, level, direction, 120):
            return resueltos

        # Actualizar zona
        zone = self._find_zone(asset, level, zone_type)
        if zone is None:
            zone = ObservedZone(asset=asset, level=level, zone_type=zone_type, first_seen_ts=now)
            self.zones.setdefault(asset, []).append(zone)
        zone.touches += 1
        zone.last_touch_ts = now
        if latest.get("is_hold", True):
            zone.holds += 1
        else:
            zone.breaks += 1
        if reaction_pips > 0:
            zone.avg_reaction_pips = zone.avg_reaction_pips * 0.7 + reaction_pips * 0.3

        # Contexto M15
        m15_trend, m15_phase, m15_rsi, m15_struct, m15_aligned = "neutral", "unknown", 50, "unknown", False
        if df_m15 is not None and len(df_m15) >= 10:
            m15_trend, m15_phase, m15_rsi, m15_struct, m15_aligned = self._analyze_m15_context(df_m15, level, direction)

        why = self._build_why(zone_type, level, reaction_pips, m15_trend, m15_aligned, m15_struct, direction, rsi_val)

        # Encolar para cada expiracion
        for exp_sec in EXPIRATIONS:
            pa = PendingAnalysis(
                id=f"{asset}_{direction}_{level:.5f}_{exp_sec}s_{int(now)}",
                asset=asset,
                entry_time=now,
                entry_price=entry_price,
                direction=direction,
                zone_type=zone_type,
                zone_level=level,
                expiration_sec=exp_sec,
                m15_trend=m15_trend,
                m15_phase=m15_phase,
                m15_rsi=m15_rsi,
                m15_structure=m15_struct,
                m15_trend_aligned=m15_aligned,
                m1_rejection_pips=reaction_pips,
                m1_rsi=rsi_val,
                why_entry=why,
            )
            self.pending.append(asdict(pa))
            self.pending = self.pending[-500:]

        self._save_pending()
        self.save()

        return resueltos + 1

    def resolve_pending_all(self, df_by_asset: Dict[str, pd.DataFrame]):
        """Resuelve todos los pendientes de todos los activos."""
        resueltos = 0
        for asset, df_m1 in df_by_asset.items():
            if df_m1 is not None and not df_m1.empty:
                resueltos += self._resolve_pending(asset, df_m1)
        self._save_analyses()
        return resueltos

    def get_opportunity(self, asset: str, direction: str, level: float) -> Tuple[bool, str, Dict]:
        """
        Evalua si una zona es confiable para operar en PRACTICE.
        Solo autoriza si tiene analisis reales completados con buen win rate.
        """
        zone_type = "support" if direction == "CALL" else "resistance"
        zone = self._find_zone(asset, level, zone_type)
        if zone is None:
            return False, "Zona sin datos de mercado", {}
        if zone.completed_analyses < MIN_ZONE_ANALYSES:
            return False, f"Solo {zone.completed_analyses}/{MIN_ZONE_ANALYSES} analisis completados", self._details(zone)
        if zone.analysis_lower_bound < 0.54:
            return False, f"Limite inferior estadístico {zone.analysis_lower_bound*100:.0f}% < 54%", self._details(zone)
        if zone.strength < 0.50:
            return False, f"Strength {zone.strength:.2f} < 0.50", self._details(zone)
        return True, f"Zona aprobada: WR={zone.analysis_win_rate*100:.0f}% ({zone.completed_analyses} analisis)", self._details(zone)

    def record_trade_result(self, asset: str, direction: str, entry: float, exit: float, result: str, level: float = 0.0):
        zone_type = "support" if direction == "CALL" else "resistance"
        zone = self._find_zone(asset, level or entry, zone_type)
        if zone is None:
            zone = ObservedZone(asset=asset, level=level or entry, zone_type=zone_type, first_seen_ts=time.time())
            self.zones.setdefault(asset, []).append(zone)
        if str(result).upper() == "WIN":
            zone.analysis_wins += 1
        elif str(result).upper() == "LOSS":
            zone.analysis_losses += 1
        zone.completed_analyses += 1
        self.save()

    def summary(self, asset: Optional[str] = None) -> Dict:
        if asset:
            zones = self.zones.get(asset, [])
        else:
            zones = [z for zlist in self.zones.values() for z in zlist]

        completados = [z for z in zones if z.completed_analyses >= 3]
        pendientes_p = len([p for p in self.pending if not p.get("resolved", False)])

        total_w = sum(z.analysis_wins for z in zones)
        total_l = sum(z.analysis_losses for z in zones)
        wr = total_w / (total_w + total_l) * 100 if (total_w + total_l) > 0 else 0

        return {
            "total_zonas": len(zones),
            "zonas_con_analisis": len([z for z in zones if z.completed_analyses > 0]),
            "listas_para_practice": len(completados),
            "analisis_pendientes": pendientes_p,
            "analisis_completados": total_w + total_l,
            "win_rate_real": wr,
            "total_toques": sum(z.touches for z in zones),
        }

    def get_completed_analyses(self, asset: Optional[str] = None, n: int = 50) -> List[Dict]:
        if asset:
            return [c for c in self.completed if c.get("asset") == asset][-n:]
        return self.completed[-n:]

    # ═══════════════════════════════════════════════════════════════
    #  RESOLVER PENDIENTES (nucleo del aprendizaje real)
    # ═══════════════════════════════════════════════════════════════

    def _resolve_pending(self, asset: str, df_m1: pd.DataFrame) -> int:
        """
        Revisa todos los pendientes de un activo.
        Si expiraron, consulta el precio REAL y determina WIN/LOSS.
        """
        now = time.time()
        resueltos = 0

        if df_m1 is None or df_m1.empty:
            return 0

        latest_close = float(df_m1["close"].iloc[-1])
        latest_high = float(df_m1["high"].iloc[-1])
        latest_low = float(df_m1["low"].iloc[-1])

        for p in self.pending:
            if p.get("asset") != asset:
                continue
            if p.get("resolved", False):
                continue

            age = now - p["entry_time"]
            if age < p["expiration_sec"]:
                continue  # aun no expira

            direction = p["direction"]
            entry = p["entry_price"]

            # Calcular MFE/MAE desde df_m1 en el periodo del trade
            entry_ts = p["entry_time"]
            df_period = df_m1[df_m1.index >= pd.Timestamp(entry_ts, unit='s')] if hasattr(df_m1.index, 'dtype') else df_m1
            if len(df_period) < 2:
                df_period = df_m1.tail(5)
            max_high = float(df_period["high"].max())
            min_low = float(df_period["low"].min())

            if direction == "CALL":
                pips = (latest_close - entry) / entry * 10000
                result = "WIN" if pips > 0 else "LOSS"
                max_fav = (max_high - entry) / entry * 10000
                max_adv = (entry - min_low) / entry * 10000
            else:
                pips = (entry - latest_close) / entry * 10000
                result = "WIN" if pips > 0 else "LOSS"
                max_fav = (entry - min_low) / entry * 10000
                max_adv = (max_high - entry) / entry * 10000

            p["resolved"] = True
            p["result"] = result
            p["exit_price"] = latest_close
            p["pips"] = round(pips, 2)
            p["max_fav_pips"] = round(max_fav, 2)
            p["max_adv_pips"] = round(max_adv, 2)
            p["resolved_ts"] = now

            # Crear analisis completado
            lesson = self._build_lesson(direction, p["zone_type"], result, p.get("m15_trend_aligned", False))
            ca = CompletedAnalysis(
                asset=asset,
                entry_time=p["entry_time"],
                entry_price=entry,
                direction=direction,
                zone_type=p["zone_type"],
                expiration_sec=p["expiration_sec"],
                result=result,
                pips=round(pips, 2),
                max_fav_pips=p.get("max_fav_pips", 0.0),
                max_adv_pips=p.get("max_adv_pips", 0.0),
                m15_trend=p.get("m15_trend", "neutral"),
                m15_phase=p.get("m15_phase", "unknown"),
                m15_rsi=p.get("m15_rsi", 50),
                m15_structure=p.get("m15_structure", "unknown"),
                m15_trend_aligned=p.get("m15_trend_aligned", False),
                m1_rejection_pips=p.get("m1_rejection_pips", 0),
                m1_rsi=p.get("m1_rsi", 50),
                why_entry=p.get("why_entry", ""),
                lesson=lesson,
            )
            self.completed.append(asdict(ca))
            self.completed = self.completed[-2000:]

            # Actualizar zona
            zone_type = p["zone_type"]
            zone = self._find_zone(asset, entry, zone_type)
            if zone:
                zone.completed_analyses += 1
                if result == "WIN":
                    zone.analysis_wins += 1
                else:
                    zone.analysis_losses += 1
                zone.avg_m15_aligned = zone.avg_m15_aligned * 0.7 + (1.0 if p.get("m15_trend_aligned", False) else 0.0) * 0.3
                zone.avg_overshoot_fav = zone.avg_overshoot_fav * 0.7 + p.get("max_fav_pips", 0) * 0.3
                zone.avg_overshoot_adv = zone.avg_overshoot_adv * 0.7 + p.get("max_adv_pips", 0) * 0.3

            resueltos += 1

        self._save_pending()
        if resueltos > 0:
            self.save()
        return resueltos

    def _has_recent_pending(self, asset: str, level: float, direction: str, max_age: float) -> bool:
        now = time.time()
        for p in self.pending:
            if p.get("asset") != asset or p.get("resolved", False):
                continue
            if p.get("direction") != direction:
                continue
            if now - p.get("entry_time", 0) > max_age:
                continue
            if abs(p.get("entry_price", 0) - level) / max(abs(level), 0.0001) <= 0.0015:
                return True
        return False

    # ═══════════════════════════════════════════════════════════════
    #  DETECCION DE SWINGS
    # ═══════════════════════════════════════════════════════════════

    def _detect_swings(self, df: pd.DataFrame, window: int = SWING_WINDOW_M1) -> List[Dict]:
        swings = []
        try:
            use_highs = df["high"].values
            use_lows = df["low"].values
            use_closes = df["close"].values
            use_opens = df["open"].values
        except (KeyError, IndexError):
            use_highs = df.iloc[:, 2].values
            use_lows = df.iloc[:, 3].values
            use_closes = df.iloc[:, 4].values
            use_opens = df.iloc[:, 1].values

        n = len(df)
        for i in range(window, n - window):
            if all(use_highs[i] >= use_highs[i - j] for j in range(1, window + 1)) and all(
                use_highs[i] >= use_highs[i + j] for j in range(1, window + 1)
            ):
                body = abs(use_closes[i] - use_opens[i])
                upper_wick = use_highs[i] - max(use_closes[i], use_opens[i])
                lower_wick = min(use_closes[i], use_opens[i]) - use_lows[i]
                if upper_wick > body * MIN_WICK_RATIO and upper_wick > lower_wick * 1.5 and body > 0:
                    rp = upper_wick / (use_highs[i] if use_highs[i] != 0 else 1) * 10000
                    if rp >= MIN_REACTION_PIPS:
                        swings.append({
                            "idx": i, "level": use_highs[i], "type": "resistance",
                            "is_hold": True, "reaction_pips": round(rp, 2),
                            "body_pct": (use_highs[i] - use_lows[i]) / (use_highs[i] if use_highs[i] != 0 else 1),
                            "timestamp": df.index[i].timestamp() if hasattr(df.index[i], "timestamp") else time.time(),
                        })

            if all(use_lows[i] <= use_lows[i - j] for j in range(1, window + 1)) and all(
                use_lows[i] <= use_lows[i + j] for j in range(1, window + 1)
            ):
                body = abs(use_closes[i] - use_opens[i])
                upper_wick = use_highs[i] - max(use_closes[i], use_opens[i])
                lower_wick = min(use_closes[i], use_opens[i]) - use_lows[i]
                if lower_wick > body * MIN_WICK_RATIO and lower_wick > upper_wick * 1.5 and body > 0:
                    rp = lower_wick / (use_lows[i] if use_lows[i] != 0 else 1) * 10000
                    if rp >= MIN_REACTION_PIPS:
                        swings.append({
                            "idx": i, "level": use_lows[i], "type": "support",
                            "is_hold": True, "reaction_pips": round(rp, 2),
                            "body_pct": (use_highs[i] - use_lows[i]) / (use_lows[i] if use_lows[i] != 0 else 1),
                            "timestamp": df.index[i].timestamp() if hasattr(df.index[i], "timestamp") else time.time(),
                        })
        return swings

    # ═══════════════════════════════════════════════════════════════
    #  CONTEXTO M15
    # ═══════════════════════════════════════════════════════════════

    def _analyze_m15_context(self, df: pd.DataFrame, level: float, direction: str) -> Tuple:
        closes = df["close"].values if "close" in df.columns else df.iloc[:, 4].values
        highs = df["high"].values if "high" in df.columns else df.iloc[:, 2].values
        lows = df["low"].values if "low" in df.columns else df.iloc[:, 3].values

        rsi_val = self._calc_rsi(df, len(df) - 1)
        ema_fast = self._ema(closes, 5)
        ema_slow = self._ema(closes, 13)
        trend = "neutral"
        if len(ema_fast) > 1 and len(ema_slow) > 1:
            if ema_fast[-1] > ema_slow[-1]:
                trend = "bullish"
            elif ema_fast[-1] < ema_slow[-1]:
                trend = "bearish"

        avg_range = np.mean(highs[-10:] - lows[-10:]) if len(highs) >= 10 else 0
        avg_close = np.mean(closes[-10:]) if len(closes) >= 10 else 1
        if avg_close > 0 and avg_range / avg_close > 0.005:
            phase = "volatile"
        else:
            phase = "ranging"

        support_near = any(abs(l - level) / max(abs(level), 0.0001) <= 0.002 for l in lows[-5:])
        resistance_near = any(abs(h - level) / max(abs(level), 0.0001) <= 0.002 for h in highs[-5:])
        if direction == "CALL" and support_near:
            structure = "support_test"
        elif direction == "PUT" and resistance_near:
            structure = "resistance_test"
        elif (direction == "CALL" and trend == "bullish") or (direction == "PUT" and trend == "bearish"):
            structure = "pullback"
        else:
            structure = "unknown"

        aligned = (direction == "CALL" and trend == "bullish") or (direction == "PUT" and trend == "bearish")
        return trend, phase, round(rsi_val, 1), structure, aligned

    # ═══════════════════════════════════════════════════════════════
    #  EXPLICACIONES Y LECCIONES
    # ═══════════════════════════════════════════════════════════════

    def _build_why(self, zone_type: str, level: float, rejection: float,
                   trend: str, aligned: bool, structure: str, direction: str, rsi: float) -> str:
        parts = []
        parts.append(f"{zone_type.title()} en {level:.5f}")
        parts.append(f"Rechazo M1 de {rejection:.1f} pips")
        if aligned:
            parts.append(f"Tendencia M15 a favor ({trend})")
        else:
            parts.append(f"Contra tendencia M15 ({trend})")
        if structure != "unknown":
            parts.append(f"Estructura: {structure}")
        if direction == "CALL" and rsi < 35:
            parts.append(f"RSI M1 sobrevendido ({rsi:.0f})")
        elif direction == "PUT" and rsi > 65:
            parts.append(f"RSI M1 sobrecomprado ({rsi:.0f})")
        return " | ".join(parts)

    def _build_lesson(self, direction: str, zone_type: str, result: str, aligned: bool) -> str:
        base = f"{direction} en {zone_type}"
        if result == "WIN":
            if aligned:
                return f"{base} con tendencia M15 a favor = GANA"
            return f"{base} sin tendencia M15 a favor = GANA (excepcional)"
        else:
            if not aligned:
                return f"{base} contra tendencia M15 = PIERDE"
            return f"{base} con tendencia M15 a favor = PIERDE (senial debil)"

    # ═══════════════════════════════════════════════════════════════
    #  INDICADORES TECNICOS
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    def _calc_rsi(df: pd.DataFrame, idx: int, period: int = 14) -> float:
        try:
            closes = df["close"].values if "close" in df.columns else df.iloc[:, 4].values
        except (KeyError, IndexError):
            return 50.0
        n = len(closes)
        start = max(0, idx - period - 5)
        end = min(n, idx + 1)
        segment = closes[start:end]
        if len(segment) < period + 1:
            return 50.0
        deltas = np.diff(segment)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        avg_gain = float(np.mean(gains[-period:])) if len(gains) >= period else float(np.mean(gains))
        avg_loss = float(np.mean(losses[-period:])) if len(losses) >= period else float(np.mean(losses))
        if avg_loss == 0:
            return 100.0 if avg_gain > 0 else 50.0
        return 100.0 - (100.0 / (1.0 + avg_gain / avg_loss))

    @staticmethod
    def _ema(values: np.ndarray, period: int) -> np.ndarray:
        if len(values) < period:
            return np.array([])
        m = 2 / (period + 1)
        ema = np.zeros(len(values))
        ema[0] = values[0]
        for i in range(1, len(values)):
            ema[i] = (values[i] - ema[i - 1]) * m + ema[i - 1]
        return ema

    # ═══════════════════════════════════════════════════════════════
    #  HELPERS
    # ═══════════════════════════════════════════════════════════════

    def _find_zone(self, asset: str, level: float, zone_type: str) -> Optional[ObservedZone]:
        for zone in self.zones.get(asset, []):
            if zone.zone_type != zone_type:
                continue
            if abs(zone.level - level) / max(abs(level), 0.0001) <= 0.0015:
                return zone
        return None

    def _details(self, zone: ObservedZone) -> Dict:
        return {
            "zone_level": zone.level,
            "zone_type": zone.zone_type,
            "touches": zone.touches,
            "holds": zone.holds,
            "breaks": zone.breaks,
            "strength": zone.strength,
            "analisis_completados": zone.completed_analyses,
            "win_rate_real": zone.analysis_win_rate,
            "win_rate_lower_bound": zone.analysis_lower_bound,
            "avg_m15_aligned": round(zone.avg_m15_aligned, 2),
        }

    # ═══════════════════════════════════════════════════════════════
    #  CONVERTIR A JSON (limpiar tipos numpy)
    # ═══════════════════════════════════════════════════════════════

    def _clean(self, obj):
        if isinstance(obj, dict):
            return {k: self._clean(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self._clean(v) for v in obj]
        if isinstance(obj, (float, np.floating)):
            return float(obj)
        if isinstance(obj, (int, np.integer)):
            return int(obj)
        if isinstance(obj, (bool, np.bool_)):
            return bool(obj)
        return obj

    # ═══════════════════════════════════════════════════════════════
    #  PERSISTENCIA
    # ═══════════════════════════════════════════════════════════════

    def _load(self):
        if os.path.exists(self.persist_path):
            try:
                with open(self.persist_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for asset, raw in data.get("zones", {}).items():
                    self.zones[asset] = [
                        ObservedZone(**{k: v for k, v in zd.items() if k in ObservedZone.__dataclass_fields__})
                        for zd in raw
                    ]
            except Exception:
                self.zones = {}
        if os.path.exists(self.analysis_path):
            try:
                with open(self.analysis_path, "r", encoding="utf-8") as f:
                    self.completed = self._dedupe_completed(json.load(f))
            except Exception:
                self.completed = []
        if os.path.exists(self.pending_path):
            try:
                with open(self.pending_path, "r", encoding="utf-8") as f:
                    self.pending = self._dedupe_pending(json.load(f))
            except Exception:
                self.pending = []
        self._rebuild_analysis_stats()

    @staticmethod
    def _dedupe_completed(rows):
        """Remove the old 1/2/5-minute copies of one observed entry."""
        unique = {}
        for row in rows if isinstance(rows, list) else []:
            key = (
                row.get("asset"), row.get("direction"),
                round(float(row.get("entry_time", 0) or 0), 3),
                round(float(row.get("entry_price", 0) or 0), 8),
            )
            current = unique.get(key)
            if current is None or row.get("expiration_sec") == 180:
                unique[key] = row
        return list(unique.values())[-2000:]

    @staticmethod
    def _dedupe_pending(rows):
        unique = {}
        for row in rows if isinstance(rows, list) else []:
            key = (
                row.get("asset"), row.get("direction"),
                round(float(row.get("entry_time", 0) or 0), 3),
                round(float(row.get("entry_price", 0) or 0), 8),
            )
            current = unique.get(key)
            if current is None or row.get("expiration_sec") == 180:
                unique[key] = row
        return list(unique.values())[-500:]

    def _rebuild_analysis_stats(self):
        """Rebuild zone counters from independent completed events."""
        for zones in self.zones.values():
            for zone in zones:
                zone.completed_analyses = 0
                zone.analysis_wins = 0
                zone.analysis_losses = 0
                zone.avg_m15_aligned = 0.0
                zone.avg_overshoot_fav = 0.0
                zone.avg_overshoot_adv = 0.0
        for row in self.completed:
            zone = self._find_zone(row.get("asset"), float(row.get("entry_price", 0) or 0), row.get("zone_type"))
            if zone is None:
                continue
            zone.completed_analyses += 1
            if str(row.get("result", "")).upper() == "WIN":
                zone.analysis_wins += 1
            elif str(row.get("result", "")).upper() == "LOSS":
                zone.analysis_losses += 1

    def save(self):
        os.makedirs(os.path.dirname(self.persist_path), exist_ok=True)
        data = {"version": "4.0", "updated": time.time(),
                "zones": self._clean({a: [asdict(z) for z in zones] for a, zones in self.zones.items()})}
        with open(self.persist_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def _save_pending(self):
        os.makedirs(os.path.dirname(self.pending_path), exist_ok=True)
        with open(self.pending_path, "w", encoding="utf-8") as f:
            json.dump(self._clean(self.pending), f, indent=2)

    def _save_analyses(self):
        os.makedirs(os.path.dirname(self.analysis_path), exist_ok=True)
        with open(self.analysis_path, "w", encoding="utf-8") as f:
            json.dump(self._clean(self.completed), f, indent=2)


_learner: Optional[SupervisedZoneLearner] = None


def get_supervised_zone_learner() -> SupervisedZoneLearner:
    global _learner
    if _learner is None:
        _learner = SupervisedZoneLearner()
    return _learner
