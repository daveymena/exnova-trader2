# -*- coding: utf-8 -*-
"""Broker de papel. Sin llamadas externas y SIN inventarse resultados.

CAMBIO ESTRUCTURAL
------------------
La version anterior tenia `_simulate_result()` devolviendo
`random.random() < 0.5`. Es decir: el modo paper resolvia cada operacion con
una moneda al aire. No era "simulacion conservadora", era ruido etiquetado
como resultado, y ademas el modo paper no podia medir absolutamente nada.

Peor: `PaperBroker` no tenia `get_last_close`, asi que
`app/main.py::_resolve_with_evidence()` devolvia False SIEMPRE en modo paper y
toda operacion acababa en `ExecutionState.UNKNOWN` tras el timeout. El modo por
defecto del proyecto era un bucle que abria operaciones y nunca las cerraba.

Ahora el PaperBroker NO resuelve nada: registra la orden y lleva la
contabilidad. Quien resuelve es `app/core/engine.py`, contra el precio del
`MarketFeed`. Eso tiene dos consecuencias buenas:

  1. El resultado depende del precio observado, no de un dado.
  2. La procedencia del precio (`feed.data_source`) se propaga al trade, y
     `EVIDENCE_SQL` decide si cuenta. Paper sobre simulador -> no evidencia.
     Paper sobre replay CSV real -> evidencia. Broker en vivo -> evidencia.

El modo paper pasa de ser inutil a ser el banco de pruebas del motor: mismo
codigo que en vivo, distinta fuente de precios.
"""
from __future__ import annotations

import itertools
from datetime import datetime, timedelta
from typing import Optional

from app.data.schemas import (
    DataSource, Direction, EntryTiming, ExecutionState, MarketRegime,
    ResolutionSource, TradeResult,
)
from app.services.broker_base import BrokerBase

_counter = itertools.count(1)


class PaperBroker(BrokerBase):
    """Broker simulado. Resolucion delegada al motor contra el feed."""

    data_source = DataSource.SIMULATOR

    def __init__(self, initial_balance: float = 10_000.0,
                 data_source: DataSource = DataSource.SIMULATOR,
                 min_stake: float = 1.0, max_stake: float = 1_000.0):
        super().__init__(initial_balance)
        # La procedencia la fija quien construye el broker: un PaperBroker
        # alimentado por un ReplayFeed de CSV historico REAL marca sus trades
        # como CSV y por tanto SI producen evidencia. Uno alimentado por el
        # simulador los marca SIMULATOR y no producen ninguna.
        self.data_source = data_source
        self.connected = True
        self.min_stake = min_stake
        self.max_stake = max_stake
        self.mode = "paper"

    def buy(self, asset: str, direction: Direction, amount: float,
            expiry_sec: int, meta: Optional[dict] = None) -> Optional[TradeResult]:
        meta = meta or {}
        if direction == Direction.NO_TRADE:
            return None
        if amount <= 0:
            return None

        stake = round(amount, 2)
        if stake < self.min_stake or stake > self.max_stake:
            # Fuera de limites: se RECHAZA, no se recorta. Recortar hacia abajo
            # seria un sizing que el gestor de riesgo no autorizo; recortar
            # hacia arriba (min_stake) peor aun. Si el tamano pedido no es
            # operable, la respuesta correcta es no operar.
            return None
        if stake > self.balance:
            # Sin saldo no hay operacion. No se permite apostar en negativo ni
            # se ajusta el stake a la baja en silencio: un sizing que el broker
            # recorta por su cuenta es un sizing que el gestor de riesgo no
            # autorizo.
            return None

        now: datetime = meta.get("entry_time") or datetime.utcnow()
        expiry_time: datetime = meta.get("expiry_time") or now + timedelta(seconds=expiry_sec)
        order_id = f"paper_{next(_counter)}_{asset}_{direction.value}"

        trade = TradeResult(
            timestamp=now,
            asset=asset,
            direction=direction,
            strategy=meta.get("strategy", ""),
            expiry=expiry_sec,
            payout=meta.get("payout", 0.85),
            stake=stake,
            # RESULT = 0.0 AL ABRIR. Ni -stake (PaperBroker viejo: contaba una
            # perdida inexistente) ni nada que el gestor de riesgo pueda leer
            # como resultado. Un trade abierto no ha ganado ni perdido.
            result=0.0,
            execution_state=ExecutionState.SENT,
            market_regime=(meta.get("market_regime")
                           if isinstance(meta.get("market_regime"), MarketRegime)
                           else MarketRegime.UNKNOWN),
            confidence=meta.get("confidence", 0.0),
            entry_timing=meta.get("entry_timing") or EntryTiming.NO_TRADE,
            features={
                "order_id": order_id,
                "mode": "paper",
                "strategy_confidence": meta.get("confidence", 0.0),
                "setup_slug": meta.get("setup_slug", ""),
                "stake_multiplier": meta.get("stake_multiplier", 1.0),
                **{k: v for k, v in (meta.get("features") or {}).items()},
            },
            entry_price=meta.get("entry_price"),
            entry_time=now,
            expiry_time=expiry_time,
            broker_order_id=order_id,
            resolution_source=ResolutionSource.UNRESOLVED,
            data_source=meta.get("data_source", self.data_source),
        )

        self.balance -= stake
        self.equity = self.balance
        self.open_trades.append(trade)
        return trade

    def get_equity(self) -> float:
        """Balance disponible: el stake de las abiertas ya se desconto."""
        return self.balance

    def get_balance(self) -> float:
        return self.balance

    # ── compatibilidad con codigo que aun llama al API viejo ──────────────

    def expire_all(self, *args, **kwargs) -> list[TradeResult]:
        """Intencionadamente inerte.

        El PaperBroker antiguo resolvia aqui con moneda al aire. Se deja el
        metodo para no romper llamadas heredadas, pero NO resuelve nada: la
        resolucion es del motor, contra el feed. Devolver [] es la respuesta
        honesta.
        """
        return []
