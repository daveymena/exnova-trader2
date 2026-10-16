"""Consensus Winning Strategy - bot ganador milimetrico.

Combina todas las estrategias del sistema mediante votacion, pero NO de forma
ingenua: cada estrategia solo puede votar en el regimen de mercado donde la
auditoria (scripts/research_strategy_audit.py -> reports/strategy_audit.json)
demostro que tiene edge. Una estrategia que pierde dinero en ese regimen no
vota, aunque su logica interna diga que si.

Mapa de votantes (medido, no supuesto):

    TREND_UP / TREND_DOWN : sr_bounce, breakout_direct
    RANGE                 : sr_bounce, mean_reversion
    UNKNOWN               : breakout_direct
    HIGH_VOLATILITY       : (nadie: se mide por debajo del break-even)
    LOW_LIQUIDITY/NEWS    : (nadie)

Cuando se le pasa un `EdgeLedger`, el mapa de votantes deja de ser una
constante: el registro mide el edge REAL de cada estrategia en cada regimen y
su respuesta reemplaza al mapa sintetico en cuanto existe muestra suficiente.
Asi el bot aprende de sus propias operaciones en lugar de repetir para siempre
lo que se midio una vez sobre datos inventados.

Reglas de decision:

    - Alineacion multi-timeframe 'conflict' -> NO OPERAR.
    - Ganar la votacion exige >= 2 estrategias de acuerdo en la direccion.
    - Con un solo voto se acepta solo si su confianza >= high_conviction y el
      multi-timeframe no esta en conflicto.
    - Confianza final = max(confianzas) + 0.05 por voto extra, tope 0.95.
    - Sin votacion suficiente -> NO_TRADE (calidad sobre cantidad).
"""
from typing import Optional, List
import statistics

from app.data.schemas import Candle, Direction, MarketRegime
from app.agents.market_regime_agent import MarketRegimeAgent
from app.agents.multi_timeframe_agent import MultiTimeframeAgent
from app.strategies.sr_bounce import SRBounceStrategy
from app.strategies.trend_continuation import TrendContinuationStrategy
from app.strategies.breakout_retest import BreakoutRetestStrategy
from app.strategies.mean_reversion import MeanReversionStrategy
from app.strategies.breakout_direct import BreakoutDirectStrategy

# Quien puede votar en cada regimen. Se cambio cada vez que la auditoria
# muestra que un votante pierde dinero; no es una preferencia de diseno.
# ---------------------------------------------------------------------------
# Mapa de votantes, CALIBRADO SOBRE DATOS REALES DE MERCADO.
#
# La version anterior de este mapa salio de medir sobre datos SINTETICOS que
# generamos nosotros. En sintetico, breakout_direct daba 90.8% de acierto y
# era el pilar del consenso. Sobre 6 meses de velas M1 REALES de EURUSD
# (189.634 velas, 2026-03 a 2026-09) ese mismo breakout_direct da entre 46% y
# 49%: PIERDE DINERO en todas las celdas, con muestras de mas de mil trades.
#
# Ese 90.8% era sobreajuste: el codigo acierta contra velas que nosotros
# fabricamos, no contra el mercado. Se audito con el horizonte correcto
# (velas M1, expiracion de 3 barras = 3 minutos) y solo dos celdas
# sobreviven al test estadistico:
#
#   sr_bounce  call  trend_up    n=33   WR 69.7%   Wilson95 61.7%  -> PASA
#   sr_bounce  put   trend_down  n=61   WR 85.2%   Wilson95 80.4%  -> PASA
#
# Umbral: break-even de payout 0.85 (54.05%) + margen de seguridad (3%) =
# 57.05%. Todo lo demas queda por debajo, sobre todo con muestra grande:
# trend_continuation put/trend_down n=17.234 da 52.2%, mean_reversion
# call/range n=5.890 da 51.2%.
#
# Las dos celdas que pasan tienen muestra pequena (n=33 y n=61) y comparten
# un patron sospechoso: apuestan a favor de la tendencia que el clasificador
# de regimen acaba de detectar. Parte del acierto puede ser inercia del
# mercado, no skill de la estrategia. Por eso el EdgeLedger manda sobre este
# mapa en cuanto haya operaciones reales del broker que lo confirmen o lo
# desmientan.
VOTERS_BY_REGIME = {
    MarketRegime.TREND_UP: ("sr_bounce",),
    MarketRegime.TREND_DOWN: ("sr_bounce",),
    MarketRegime.RANGE: (),
    # UNKNOWN no vota. El regimen "desconocido" agrupa desde tendencias
    # suaves (donde breakout_direct acertaba ~78%) hasta mercados de
    # volatilidad uniforme (donde bajaba a 42%). Sin una etiqueta fiable no
    # hay forma de separar esos dos casos, y la muestra agregada no basta
    # para justificar operar ahi.
}

# Regimenes donde la medicion dice que nadie tiene edge.
NO_VOTE_REGIMES = (MarketRegime.HIGH_VOLATILITY, MarketRegime.LOW_LIQUIDITY,
                   MarketRegime.NEWS_RISK)

# Direcciones con edge medido por regimen, sobre los mismos datos reales.
# El regimen solo autoriza estrategias; esto autoriza el LADO. Sin esto, en
# trend_up se permitia sr_bounce votando PUT, que en datos reales da 44.5%
# (n=634): pierde dinero. La direccion se restringe a la que se midio.
DIRECCIONES_MEDIDAS = {
    MarketRegime.TREND_UP: ("call",),
    MarketRegime.TREND_DOWN: ("put",),
    MarketRegime.RANGE: (),
    MarketRegime.UNKNOWN: (),
    MarketRegime.HIGH_VOLATILITY: (),
}

# Ventana de volatilidad aceptable, medida como percentil del ATR actual
# frente al ATR de las ultimas ventanas. Por encima de 0.85 el movimiento es
# tan brusco que los breakouts fallan (medido: 43.6% de acierto); por debajo
# de 0.10 no hay movimiento que cubra el break-even.
VOL_PERCENTILE_MAX = 0.85
VOL_PERCENTILE_MIN = 0.10


class ConsensusWinningStrategy:
    def __init__(self, config: Optional[dict] = None):
        self.config = config or {}
        self.min_confidence = self.config.get("min_confidence", 0.65)
        self.high_conviction_threshold = self.config.get("high_conviction_threshold", 0.70)
        self.min_votes = self.config.get("min_votes", 2)
        self._conviction_needed = self.high_conviction_threshold
        self.require_mtf_agreement = self.config.get("require_mtf_agreement", True)
        # Puente con el aprendizaje real. Sin ledger, el mapa de votantes es
        # la constante medida sobre datos sinteticos.
        self.edge_ledger = self.config.get("edge_ledger")

        self.regime_agent = MarketRegimeAgent()
        self.mtf_agent = MultiTimeframeAgent()
        self.strategies = {
            "sr_bounce": SRBounceStrategy(config=self.config.get("sr_bounce", {})),
            "trend_continuation": TrendContinuationStrategy(config=self.config.get("trend_continuation", {})),
            "breakout_retest": BreakoutRetestStrategy(config=self.config.get("breakout_retest", {})),
            "mean_reversion": MeanReversionStrategy(config=self.config.get("mean_reversion", {})),
            "breakout_direct": BreakoutDirectStrategy(config=self.config.get("breakout_direct", {})),
        }

    # ------------------------------------------------------------------ #
    def evaluate(self, candles_m15: list[Candle], candles_m5: list[Candle],
                 candles_m1: list[Candle], asset: str = "") -> dict:
        reasons: List[str] = []
        features: dict = {}

        m15_sorted = sorted(candles_m15, key=lambda c: c.open_time)
        m5_sorted = sorted(candles_m5, key=lambda c: c.open_time)
        m1_sorted = sorted(candles_m1, key=lambda c: c.open_time)

        if len(m15_sorted) < 10 or len(m5_sorted) < 10 or len(m1_sorted) < 5:
            reasons.append("Datos insuficientes")
            return self._reject(reasons, features)

        # --- 1. Regimen de mercado (M15 manda) ---
        regime_snapshot = self.regime_agent.classify(m15_sorted, asset)
        regime = regime_snapshot.regime
        features["regime"] = regime.value
        features["m15_adx"] = regime_snapshot.adx
        features["m15_atr_percentile"] = regime_snapshot.atr_percentile

        if regime in NO_VOTE_REGIMES:
            reasons.append(f"Regimen {regime.value}: nadie tiene edge medido ahi")
            return self._reject(reasons, features, regime)

        allowed = self._voters_for(regime)
        if not allowed:
            reasons.append(f"Regimen {regime.value}: nadie tiene edge medido")
            return self._reject(reasons, features, regime)
        features["voters_allowed"] = list(allowed)
        features["voters_source"] = ("edge_ledger" if self._using_ledger(regime)
                                     else "mapa_sintetico")

        # --- 2. Alineacion multi-timeframe ---
        alignment = "unknown"
        try:
            mtf = self.mtf_agent.analyze(m15_sorted, m5_sorted, m1_sorted, asset)
            alignment = mtf.alignment
            features["mtf_alignment"] = alignment
            features["m15_trend"] = mtf.m15_trend
            features["m5_trend"] = mtf.m5_trend
            features["m1_trend"] = mtf.m1_trend
        except Exception:
            alignment = "unknown"
            features["mtf_alignment"] = alignment

        if alignment == "conflict":
            reasons.append("Multi-timeframe en conflicto: no se opera")
            return self._reject(reasons, features, regime)

        # En regimen UNKNOWN nadie demostro edge de forma robusta: se exige
        # mas conviccion y que los timeframes no sean neutrales.
        conviction_needed = self.high_conviction_threshold
        if regime == MarketRegime.UNKNOWN:
            conviction_needed = self.config.get("unknown_conviction", 0.80)
            if alignment not in ("agree", "partial"):
                reasons.append("Regimen desconocido sin multi-timeframe a favor")
                return self._reject(reasons, features, regime)
        self._conviction_needed = conviction_needed

        # --- 3. Volatilidad minima (sin mercado no hay trade) ---
        atr = self._compute_atr(m5_sorted)
        features["atr"] = round(atr, 4)
        if atr <= 0:
            reasons.append("ATR invalido")
            return self._reject(reasons, features, regime)

        vol_pct = self._atr_percentile(m5_sorted)
        features["atr_percentile"] = round(vol_pct, 4)
        if vol_pct > VOL_PERCENTILE_MAX:
            reasons.append(f"Volatilidad extrema (percentil {vol_pct:.2f} > "
                           f"{VOL_PERCENTILE_MAX}): los breakouts fallan")
            return self._reject(reasons, features, regime)
        if vol_pct < VOL_PERCENTILE_MIN:
            reasons.append(f"Mercado sin movimiento (percentil {vol_pct:.2f})")
            return self._reject(reasons, features, regime)

        # --- 4. Votacion de los estrategas autorizados ---
        votes = {"call": [], "put": []}
        strategy_results = {}
        for name in allowed:
            strategy = self.strategies[name]
            try:
                sig = strategy.evaluate(m15_sorted, m5_sorted, m1_sorted, asset)
            except Exception as exc:  # una estrategia rota no veta a las demas
                sig = {"direction": Direction.NO_TRADE, "confidence": 0.0,
                       "reasons": [f"{name}: {exc}"], "expiry": 0}
            strategy_results[name] = sig
            direction = sig.get("direction", Direction.NO_TRADE)
            conf = float(sig.get("confidence", 0.0) or 0.0)
            if direction == Direction.CALL:
                votes["call"].append((name, conf, sig))
            elif direction == Direction.PUT:
                votes["put"].append((name, conf, sig))

        features["votes_call"] = len(votes["call"])
        features["votes_put"] = len(votes["put"])
        features["strategy_votes"] = {
            n: self._dir_value(strategy_results[n].get("direction"))
            for n in strategy_results
        }

        # --- 5. Quien gana la votacion ---
        call_count, put_count = len(votes["call"]), len(votes["put"])
        winning_side = None
        winning_votes: list = []

        if call_count >= self.min_votes and call_count > put_count:
            winning_side, winning_votes = "call", votes["call"]
        elif put_count >= self.min_votes and put_count > call_count:
            winning_side, winning_votes = "put", votes["put"]
        elif call_count == 1 and put_count == 0:
            winning_side, winning_votes = self._single_vote_case(votes["call"], "call", alignment, reasons)
        elif put_count == 1 and call_count == 0:
            winning_side, winning_votes = self._single_vote_case(votes["put"], "put", alignment, reasons)

        if winning_side is None:
            reasons.append(f"Sin consenso: CALL={call_count} PUT={put_count} "
                           f"(votantes: {', '.join(allowed)})")
            return self._reject(reasons, features, regime)

        # --- 5b. El lado ganador tiene que ser uno de los medidos ---
        # El regimen autoriza estrategias; DIRECCIONES_MEDIDAS autoriza el
        # lado. En datos reales sr_bounce acertaba call en trend_up (69.7%)
        # pero PUT en trend_up daba 44.5% con n=634: pierde dinero. Sin este
        # filtro el consenso podia elegir ese lado perdedor.
        lados_medidos = DIRECCIONES_MEDIDAS.get(regime, ())
        features["direcciones_medidas"] = list(lados_medidos)
        if winning_side not in lados_medidos:
            reasons.append(
                f"Lado {winning_side.upper()} sin edge medido en regimen "
                f"{regime.value} (medidos: {list(lados_medidos) or 'ninguno'})")
            return self._reject(reasons, features, regime)

        # --- 6. Construir la senal ganadora ---
        direction = Direction.CALL if winning_side == "call" else Direction.PUT
        base_conf = max(v[1] for v in winning_votes)
        confidence = min(0.95, base_conf + 0.05 * (len(winning_votes) - 1))

        if confidence < self.min_confidence:
            reasons.append(f"Confianza {confidence:.2f} por debajo de {self.min_confidence}")
            return self._reject(reasons, features, regime)

        best = max(winning_votes, key=lambda v: v[1])[2]
        expiry = int(best.get("expiry") or 0)
        if expiry <= 0:
            expiry = 180

        features["consensus_votes"] = len(winning_votes)
        features["consensus_confidence"] = round(confidence, 4)
        features["winning_strategies"] = [v[0] for v in winning_votes]

        return {
            "direction": direction,
            "strategy": "consensus_winning",
            "market_regime": regime,
            "entry_rationale": (
                f"Consenso {winning_side.upper()} de {len(winning_votes)}/"
                f"{len(allowed)} estrategias con edge en {regime.value}"
            ),
            "invalidation": best.get("invalidation", "consenso invalidado"),
            "confidence": round(confidence, 4),
            "features": features,
            "expiry": expiry,
            "reasons": [f"consensus_{winning_side}"],
            "skip_entry_timing": any(
                v[2].get("skip_entry_timing") for v in winning_votes
            ),
        }

    # ------------------------------------------------------------------ #
    def _voters_for(self, regime: MarketRegime) -> tuple[str, ...]:
        """Quien vota en este regimen: el registro real si sabe, el mapa
        sintetico si aun no hay muestra."""
        static = VOTERS_BY_REGIME.get(regime, ())
        if self.edge_ledger is None:
            return tuple(static)
        try:
            return tuple(self.edge_ledger.voters_for(regime, fallback=static))
        except Exception:
            # El registro es una mejora, no una dependencia: si falla la
            # lectura de SQLite se sigue con lo medido en la auditoria.
            return tuple(static)

    def _using_ledger(self, regime: MarketRegime) -> bool:
        if self.edge_ledger is None:
            return False
        try:
            measured = self.edge_ledger.measure_all()
        except Exception:
            return False
        return any(m.regime == regime.value and m.has_edge
                   for m in measured.values())

    def _single_vote_case(self, side_votes, side, alignment, reasons):
        """Un solo voto solo pasa con alta conviccion y sin conflicto de TFs."""
        name, conf, _ = side_votes[0]
        threshold = getattr(self, "_conviction_needed", self.high_conviction_threshold)
        if conf < threshold:
            reasons.append(f"Voto unico de {name} con confianza {conf:.2f} "
                           f"< {threshold}")
            return None, []
        if self.require_mtf_agreement and alignment not in ("agree", "partial"):
            reasons.append(f"Voto unico de {name} sin multi-timeframe a favor")
            return None, []
        return side, side_votes

    @staticmethod
    def _dir_value(direction) -> str:
        return direction.value if hasattr(direction, "value") else str(direction)

    PERCENTILE_WINDOWS = 60

    def _atr_percentile(self, candles: list[Candle]) -> float:
        """Percentil del ATR actual frente al ATR de las ventanas recientes."""
        span = 14
        if len(candles) < span * 2:
            return 0.5
        first = max(0, len(candles) - span - self.PERCENTILE_WINDOWS)
        samples = [self._compute_atr(candles[i:i + span])
                   for i in range(first, len(candles) - span)]
        if not samples:
            return 0.5
        current = self._compute_atr(candles)
        return sum(1 for v in samples if v < current) / len(samples)

    @staticmethod
    def _compute_atr(candles: list[Candle]) -> float:
        if len(candles) < 2:
            return 0.0
        tr = []
        for i in range(1, len(candles)):
            hl = candles[i].high - candles[i].low
            hc = abs(candles[i].high - candles[i - 1].close)
            lc = abs(candles[i].low - candles[i - 1].close)
            tr.append(max(hl, hc, lc))
        period = min(14, len(tr))
        return statistics.mean(tr[-period:]) if period > 0 else 0.0

    def _reject(self, reasons: list, features: dict,
                regime: MarketRegime = MarketRegime.UNKNOWN) -> dict:
        return {
            "direction": Direction.NO_TRADE,
            "strategy": "consensus_winning",
            "market_regime": regime,
            "entry_rationale": "; ".join(reasons) if reasons else "sin senal",
            "invalidation": "not_applicable",
            "confidence": 0.0,
            "features": features,
            "expiry": 0,
            "reasons": reasons,
        }
