# -*- coding: utf-8 -*-
"""Contrato de broker.

POR QUE EXISTE
--------------
`PaperBroker` y `ExnovaBroker` tenian semanticas DIFERENTES para el mismo
campo, y eso rompia el gestor de riesgo (punto 7 de la auditoria):

  * `PaperBroker.buy()` inicializaba `result = -amount` (la perdida ya
    contabilizada antes de saber nada).
  * `ExnovaBroker._register_sent()` inicializaba `result = 0.0`.

El `RiskManagerAgent.record_trade_result()` hacia `if result.result < 0:
consecutive_losses += 1`. Con PaperBroker contaba una perdida que aun no habia
ocurrido; con ExnovaBroker el contador NUNCA crecia, porque el resultado se
quedaba en 0.0 hasta la resolucion y para entonces ya se habia llamado al
contador. Resultado: el corte de seguridad por racha de perdidas no podia
dispararse jamas en modo practice/real -- exactamente donde hace falta.

La regla ahora es unica y esta escrita aqui: al ABRIR, `result` es 0.0 y
`resolution_source` es UNRESOLVED. Un trade abierto no ha ganado ni perdido.
Solo `settle()` escribe el resultado, y solo lo llama quien tiene evidencia.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from app.data.schemas import (
    DataSource, Direction, ExecutionState, ResolutionSource, TradeResult,
)


class BrokerBase(ABC):
    """Interfaz minima que el motor necesita de cualquier broker."""

    #: De donde vienen los precios que este broker usa. Determina si lo que
    #: resuelva cuenta como evidencia.
    data_source: DataSource = DataSource.UNKNOWN

    def __init__(self, initial_balance: float = 10_000.0):
        self.balance = float(initial_balance)
        self.equity = float(initial_balance)
        self.open_trades: list[TradeResult] = []
        self.connected: bool = False

    # ── ordenes ──────────────────────────────────────────────────────────

    @abstractmethod
    def buy(self, asset: str, direction: Direction, amount: float,
            expiry_sec: int, meta: Optional[dict] = None) -> Optional[TradeResult]:
        """Abre una operacion. None si el broker la rechazo o no pudo enviarla.

        `meta` lleva strategy, market_regime, confidence, entry_price,
        entry_time, expiry_time y data_source. El broker NO decide la
        resolucion: solo registra la orden.
        """

    def settle(self, trade: TradeResult, won: bool, payout: float,
               exit_price: Optional[float] = None,
               resolution_source: ResolutionSource = ResolutionSource.CANDLE,
               data_source: Optional[DataSource] = None) -> TradeResult:
        """Cierra la operacion con un resultado YA determinado por evidencia.

        Unico sitio donde se escribe `trade.result`. Contabilidad: el stake se
        desconto en `buy()`, asi que al ganar se devuelve stake + beneficio y
        al perder no se devuelve nada.
        """
        trade.payout = payout
        if won:
            profit = trade.stake * payout
            trade.result = profit
            trade.execution_state = ExecutionState.WON
            self.balance += trade.stake + profit
        else:
            trade.result = -trade.stake
            trade.execution_state = ExecutionState.LOST
        if exit_price is not None:
            trade.exit_price = exit_price
        trade.resolution_source = resolution_source
        # PROPAGACION DE PROCEDENCIA.
        #
        # La version anterior solo escribia `data_source` si el llamador lo
        # pasaba explicitamente. Un trade creado sin declarar su procedencia se
        # quedaba en UNKNOWN para siempre, y UNKNOWN no es evidencia -- asi que
        # un PaperBroker alimentado por un replay CSV REAL nunca aportaba
        # evidencia. Fallaba hacia el lado seguro (no contar) pero rompia justo
        # lo que hace util al forward test: operar en papel sobre precios reales
        # para medir sin arriesgar.
        #
        # El broker sabe a que feed esta conectado. Si el trade no lo declara, se
        # hereda del broker; si el trade YA lo declara, se respeta (el trade sabe
        # mas que el broker sobre su propio origen).
        if data_source is not None:
            trade.data_source = data_source
        elif trade.data_source == DataSource.UNKNOWN and \
                getattr(self, "data_source", DataSource.UNKNOWN) != DataSource.UNKNOWN:
            trade.data_source = self.data_source
        self.equity = self.balance
        self.open_trades = [t for t in self.open_trades if t is not trade]
        return trade

    def refund(self, trade: TradeResult, reason: str = "empate") -> TradeResult:
        """Devuelve el stake sin resultado. Es lo que hace un broker cuando la
        binaria liquida en empate (close == entry): no es victoria ni derrota,
        y contabilizarla como derrota sesgaria el win rate a la baja.

        Queda como `ExecutionState.UNKNOWN` + `resolution_source=UNRESOLVED`:
        no es evidencia y no entra en el calculo de edge.
        """
        self.balance += trade.stake
        trade.result = 0.0
        trade.execution_state = ExecutionState.UNKNOWN
        trade.resolution_source = ResolutionSource.UNRESOLVED
        trade.error = reason
        self.equity = self.balance
        self.open_trades = [t for t in self.open_trades if t is not trade]
        return trade

    # ── cuenta ───────────────────────────────────────────────────────────

    def get_balance(self) -> float:
        return self.balance

    def get_equity(self) -> float:
        """Balance menos el stake inmovilizado en operaciones abiertas."""
        return self.balance

    def resolve_order(self, order_id) -> Optional[float]:
        """PnL que el broker reporta para una orden. None si no sabe.

        Solo los brokers reales lo implementan. Es la fuente de evidencia de
        maxima calidad: `ResolutionSource.BROKER`.
        """
        return None

    def disconnect(self) -> None:
        self.connected = False
