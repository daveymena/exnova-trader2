"""Database repository for all persistent data."""
import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.config import config
from app.data.schemas import (
    Candle, MarketRegimeSnapshot, MultiTimeframeSnapshot,
    Signal, TradeDecision, TradeResult, AccountSnapshot,
    Timeframe, MarketRegime, Direction, RiskDecision, ExecutionState,
    TradingMode, EntryTiming, BacktestResult, ResolutionSource, DataSource,
    SetupKey, SetupRecord, SetupState, SetupVerdict,
    ImprovementProposal, BacktestRun,
)
from app.stats.core import (
    wilson_lower_bound, wilson_interval, summarize_binomial, breakeven_winrate,
)

# Solo estas fuentes de resolución cuentan como evidencia estadística.
# Las operaciones simuladas o sin resolver quedan fuera de todo cálculo de edge.
#
# CORRECCION: la version anterior solo miraba `resolution_source`. Con un
# PaperBroker alimentado por el simulador de microestructura, toda operacion
# acababa con resolution_source='candle' (resuelta contra un precio observado)
# sobre un precio SINTETICO. Pasaba el filtro y el EdgeValidator aprendia edge
# de ruido. Ahora se exigen las dos cosas: resolucion real Y precio real.
EVIDENCE_SQL = (
    "resolution_source IN ('broker', 'candle') "
    "AND COALESCE(data_source, 'unknown') IN ('broker', 'csv')"
)


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


def _parse_dt(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _col(row: sqlite3.Row, name: str, default=None):
    """sqlite3.Row no tiene .get(); esto lo suple sin reventar si falta la columna."""
    try:
        value = row[name]
    except (IndexError, KeyError):
        return default
    return default if value is None else value


class Repository:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or config.database_path
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None

    def connect(self):
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            # Migracion perezosa: `migrate()` es idempotente (CREATE TABLE IF
            # NOT EXISTS) y `__init__` ya creo el directorio. Sin esto, cualquier
            # consumidor que olvidara llamar a migrate() -- el EdgeValidator, el
            # SetupEvaluator, un script suelto -- reventaba con
            # "no such table: trade_results" en lugar de funcionar.
            self.migrate()
        return self._conn

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def migrate(self):
        conn = self.connect()
        cursor = conn.cursor()

        cursor.executescript("""
            CREATE TABLE IF NOT EXISTS candles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                open_time TEXT NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume REAL,
                source TEXT DEFAULT 'unknown',
                quality TEXT DEFAULT 'normal',
                data_source TEXT DEFAULT 'unknown',
                UNIQUE(asset, timeframe, open_time)
            );

            CREATE INDEX IF NOT EXISTS idx_candles_lookup
                ON candles(asset, timeframe, open_time);

            CREATE TABLE IF NOT EXISTS market_regime_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                asset TEXT NOT NULL,
                regime TEXT NOT NULL,
                adx REAL,
                atr_percentile REAL,
                ema_slope REAL,
                price_distance_ema REAL,
                features TEXT DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS multi_timeframe_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                asset TEXT NOT NULL,
                m15_regime TEXT NOT NULL,
                m5_regime TEXT NOT NULL,
                m1_regime TEXT NOT NULL,
                alignment TEXT NOT NULL,
                m15_trend TEXT,
                m5_trend TEXT,
                m1_trend TEXT
            );

            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                asset TEXT NOT NULL,
                strategy TEXT NOT NULL,
                direction TEXT NOT NULL,
                confidence REAL,
                market_regime TEXT,
                entry_timing TEXT,
                expiry INTEGER,
                payout REAL,
                rationale TEXT,
                invalidation TEXT,
                features TEXT DEFAULT '{}',
                opportunity_score REAL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS trade_decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                asset TEXT NOT NULL,
                direction TEXT NOT NULL,
                strategy TEXT,
                confidence REAL,
                opportunity_score REAL,
                market_regime TEXT,
                entry_timing TEXT,
                expiry INTEGER,
                payout REAL,
                risk_decision TEXT NOT NULL,
                risk_reason TEXT,
                edge_approved INTEGER DEFAULT 0,
                edge_details TEXT,
                ai_audit TEXT,
                execution_state TEXT DEFAULT 'pending'
            );

            CREATE TABLE IF NOT EXISTS trade_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                asset TEXT NOT NULL,
                direction TEXT NOT NULL,
                strategy TEXT,
                expiry INTEGER,
                payout REAL,
                stake REAL,
                result REAL,
                execution_state TEXT,
                market_regime TEXT,
                confidence REAL DEFAULT 0,
                entry_timing TEXT DEFAULT 'no_trade',
                features TEXT DEFAULT '{}',
                error TEXT,
                entry_price REAL,
                exit_price REAL,
                entry_time TEXT,
                expiry_time TEXT,
                resolved_at TEXT,
                broker_order_id TEXT,
                resolution_source TEXT DEFAULT 'unresolved',
                data_source TEXT DEFAULT 'unknown'
            );

            CREATE INDEX IF NOT EXISTS idx_trade_results_edge
                ON trade_results(asset, strategy, direction, market_regime, expiry);

            CREATE TABLE IF NOT EXISTS account_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                mode TEXT NOT NULL,
                equity REAL,
                balance REAL,
                daily_pnl REAL,
                daily_drawdown REAL,
                open_positions INTEGER,
                total_trades_today INTEGER
            );

            CREATE TABLE IF NOT EXISTS strategy_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                strategy_name TEXT NOT NULL,
                version TEXT NOT NULL,
                config TEXT NOT NULL,
                created_at TEXT NOT NULL,
                active INTEGER DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS errors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                source TEXT,
                level TEXT,
                message TEXT,
                traceback TEXT
            );

            CREATE TABLE IF NOT EXISTS ai_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cycle_id INTEGER NOT NULL,
                agent TEXT NOT NULL,
                event TEXT NOT NULL,
                detail TEXT,
                timestamp TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_ai_audit_cycle
                ON ai_audit(cycle_id);

            CREATE TABLE IF NOT EXISTS ai_recommendations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cycle_id INTEGER NOT NULL,
                agent TEXT NOT NULL,
                category TEXT NOT NULL,
                severity TEXT NOT NULL DEFAULT 'info',
                recommendation TEXT NOT NULL,
                proposed_config_change TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                applied_at TEXT,
                rejected_reason TEXT,
                evidence TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_ai_reco_status
                ON ai_recommendations(status, created_at);

            CREATE TABLE IF NOT EXISTS ai_overnight (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_date TEXT NOT NULL,
                summary TEXT NOT NULL,
                metrics TEXT,
                recommendations TEXT,
                model TEXT,
                tokens_used INTEGER,
                duration_sec REAL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            -- Ciclo de vida de cada setup (asset|strategy|direction|regime|expiry).
            -- Es la unidad que se mide y se opera; ver SetupState en schemas.py.
            CREATE TABLE IF NOT EXISTS setups (
                slug TEXT PRIMARY KEY,
                asset TEXT NOT NULL,
                strategy TEXT NOT NULL,
                direction TEXT NOT NULL,
                market_regime TEXT NOT NULL,
                expiry INTEGER NOT NULL,
                state TEXT NOT NULL DEFAULT 'exploracion',
                verdict TEXT NOT NULL DEFAULT 'insuficiente',
                n INTEGER NOT NULL DEFAULT 0,
                n_traded INTEGER NOT NULL DEFAULT 0,
                wins INTEGER NOT NULL DEFAULT 0,
                win_rate REAL,
                win_rate_lower REAL,
                win_rate_upper REAL,
                avg_payout REAL,
                break_even REAL,
                expectancy REAL,
                expectancy_lower REAL,
                looks INTEGER NOT NULL DEFAULT 0,
                next_checkpoint INTEGER NOT NULL DEFAULT 0,
                reopened INTEGER NOT NULL DEFAULT 0,
                variants INTEGER NOT NULL DEFAULT 0,
                stake_multiplier REAL NOT NULL DEFAULT 0.25,
                params TEXT DEFAULT '{}',
                updated_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_setups_state ON setups(state, strategy);

            -- Propuestas de mejora. El LLM propone aqui; nadie aplica desde aqui.
            CREATE TABLE IF NOT EXISTS improvement_proposals (
                id TEXT PRIMARY KEY,
                origin TEXT NOT NULL,
                target TEXT NOT NULL,
                action TEXT NOT NULL,
                payload TEXT DEFAULT '{}',
                rationale TEXT,
                evidence TEXT DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'proposed',
                created_at TEXT,
                decided_at TEXT,
                rejection_reason TEXT,
                baseline_metric REAL,
                candidate_metric REAL,
                improvement REAL
            );

            CREATE INDEX IF NOT EXISTS idx_proposals_status
                ON improvement_proposals(status, created_at);

            -- Backtests persistidos, con in-sample y out-of-sample SEPARADOS.
            CREATE TABLE IF NOT EXISTS trade_forensics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_id INTEGER,
                analysed_at TEXT,
                asset TEXT,
                strategy TEXT,
                direction TEXT,
                setup_slug TEXT,
                expiry INTEGER,
                won INTEGER,
                failure_mode TEXT NOT NULL,
                tags TEXT,
                excursions TEXT,
                rule TEXT,
                actionable_hint TEXT,
                diagnosis_confidence TEXT,
                features_at_entry TEXT,
                is_evidence INTEGER DEFAULT 0,
                data_source TEXT DEFAULT 'unknown'
            );

            CREATE INDEX IF NOT EXISTS idx_forensics_setup_mode
                ON trade_forensics(setup_slug, failure_mode);
            CREATE INDEX IF NOT EXISTS idx_forensics_mode
                ON trade_forensics(failure_mode, analysed_at);

            CREATE TABLE IF NOT EXISTS backtest_runs (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                label TEXT,
                data_source TEXT,
                asset TEXT,
                strategy TEXT,
                candles_used INTEGER,
                params TEXT DEFAULT '{}',
                in_sample TEXT DEFAULT '{}',
                out_of_sample TEXT DEFAULT '{}',
                walk_forward TEXT DEFAULT '{}',
                verdict TEXT,
                honest_note TEXT
            );
        """)
        conn.commit()
        self._migrate_trade_results_columns(conn)

    def _migrate_trade_results_columns(self, conn):
        """Añade las columnas de evidencia a bases de datos ya existentes.

        Las filas previas quedan con resolution_source='simulated' porque fueron
        generadas por el antiguo `random.random() < 0.55`: no son evidencia y no
        deben contaminar el cálculo de edge.
        """
        existing = {r[1] for r in conn.execute("PRAGMA table_info(trade_results)")}
        new_columns = {
            "entry_price": "REAL",
            "exit_price": "REAL",
            "entry_time": "TEXT",
            "expiry_time": "TEXT",
            "resolved_at": "TEXT",
            "broker_order_id": "TEXT",
            "resolution_source": "TEXT DEFAULT 'unresolved'",
            # Proveniencia del PRECIO. Sin ella un resultado resuelto contra el
            # simulador se cuela en el calculo de edge como si fuera real.
            "data_source": "TEXT DEFAULT 'unknown'",
        }
        candle_cols = {r[1] for r in conn.execute("PRAGMA table_info(candles)")}
        if "data_source" not in candle_cols:
            conn.execute(
                "ALTER TABLE candles ADD COLUMN data_source TEXT DEFAULT 'unknown'"
            )
        added = [name for name in new_columns if name not in existing]
        for name in added:
            conn.execute(f"ALTER TABLE trade_results ADD COLUMN {name} {new_columns[name]}")

        if "data_source" in added:
            # El historico previo a esta columna no registra de donde vino el
            # precio. Se marca 'unknown', que NO pasa EVIDENCE_SQL: ante la
            # duda, fuera de la estadistica. Marcarlo 'broker' o 'csv' seria
            # regalar evidencia a filas que nadie puede justificar.
            conn.execute(
                "UPDATE trade_results SET data_source='unknown' "
                "WHERE data_source IS NULL OR data_source=''"
            )

        if "resolution_source" in added:
            # Cuarentena del histórico sintético heredado.
            cur = conn.execute(
                "UPDATE trade_results SET resolution_source='simulated' "
                "WHERE resolution_source IS NULL OR resolution_source=''"
            )
            if cur.rowcount:
                print(
                    f"[MIGRACION] {cur.rowcount} operaciones historicas marcadas como "
                    "'simulated' (generadas por el resolvedor aleatorio) y excluidas "
                    "del calculo de edge."
                )
        conn.commit()

    # --- Candles ---

    def save_candle(self, candle: Candle):
        conn = self.connect()
        conn.execute(
            """INSERT OR REPLACE INTO candles
               (asset, timeframe, open_time, open, high, low, close, volume,
                source, quality, data_source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (candle.asset, candle.timeframe.value, candle.open_time.isoformat(),
             candle.open, candle.high, candle.low, candle.close,
             candle.volume, candle.source, candle.quality.value,
             candle.data_source.value)
        )
        conn.commit()

    def save_candles(self, candles: list[Candle]):
        conn = self.connect()
        for c in candles:
            conn.execute(
                """INSERT OR REPLACE INTO candles
                   (asset, timeframe, open_time, open, high, low, close, volume,
                    source, quality, data_source)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (c.asset, c.timeframe.value, c.open_time.isoformat(),
                 c.open, c.high, c.low, c.close,
                 c.volume, c.source, c.quality.value, c.data_source.value)
            )
        conn.commit()

    def get_candles(self, asset: str, timeframe: Timeframe,
                    limit: int = 100) -> list[Candle]:
        conn = self.connect()
        rows = conn.execute(
            """SELECT * FROM candles
               WHERE asset=? AND timeframe=?
               ORDER BY open_time DESC LIMIT ?""",
            (asset, timeframe.value, limit)
        ).fetchall()
        result = []
        for r in reversed(rows):
            result.append(Candle(
                asset=r["asset"],
                timeframe=Timeframe(int(r["timeframe"])),
                open_time=datetime.fromisoformat(r["open_time"]),
                open=r["open"], high=r["high"], low=r["low"], close=r["close"],
                volume=r.get("volume"), source=r.get("source", "unknown"),
                data_source=DataSource(_col(r, "data_source", "unknown")),
            ))
        return result

    # --- Signals ---

    def save_signal(self, signal: Signal):
        conn = self.connect()
        conn.execute(
            """INSERT INTO signals
               (timestamp, asset, strategy, direction, confidence, market_regime,
                entry_timing, expiry, payout, rationale, invalidation, features,
                opportunity_score)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (signal.timestamp.isoformat(), signal.asset, signal.strategy,
             signal.direction.value, signal.confidence,
             signal.market_regime.value if signal.market_regime else None,
             signal.entry_timing.value if signal.entry_timing else None,
             signal.expiry, signal.payout, signal.rationale,
             signal.invalidation, json.dumps(signal.features, default=str),
             signal.opportunity_score)
        )
        conn.commit()

    # --- Trade Decisions ---

    def save_decision(self, decision: TradeDecision):
        conn = self.connect()
        conn.execute(
            """INSERT INTO trade_decisions
               (timestamp, asset, direction, strategy, confidence, opportunity_score,
                market_regime, entry_timing, expiry, payout, risk_decision,
                risk_reason, edge_approved, edge_details, ai_audit, execution_state)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (decision.timestamp.isoformat(), decision.asset,
             decision.direction.value, decision.strategy,
             decision.confidence, decision.opportunity_score,
             decision.market_regime.value if decision.market_regime else None,
             decision.entry_timing.value if decision.entry_timing else None,
             decision.expiry, decision.payout, decision.risk_decision.value,
             decision.risk_reason, int(decision.edge_approved),
             # `default=str` a proposito: los detalles de edge llevan enums
            # (SetupState, MarketRegime) y datetimes. Sin esto una decision
            # cualquiera lanzaba TypeError dentro de `save_decision`, la
            # excepcion subia hasta `engine.step()` y TUMBABA EL MOTOR ENTERO
            # en el ciclo siguiente. Persistir no puede ser una causa de fallo
            # del trading: si el JSON no sale, se degrada a texto, no se cae.
            json.dumps(decision.edge_details or {}, default=str),
             decision.ai_audit, decision.execution_state.value)
        )
        conn.commit()

    # --- Trade Results ---

    def save_trade_result(self, result: TradeResult):
        conn = self.connect()
        conn.execute(
            """INSERT INTO trade_results
               (timestamp, asset, direction, strategy, expiry, payout, stake,
                result, execution_state, market_regime, confidence, entry_timing,
                features, error, entry_price, exit_price, entry_time, expiry_time,
                resolved_at, broker_order_id, resolution_source, data_source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (result.timestamp.isoformat(), result.asset,
             result.direction.value, result.strategy,
             result.expiry, result.payout, result.stake,
             result.result, result.execution_state.value,
             result.market_regime.value if result.market_regime else None,
             result.confidence,
             result.entry_timing.value if result.entry_timing else None,
             json.dumps(result.features, default=str), result.error,
             result.entry_price, result.exit_price,
             _iso(result.entry_time), _iso(result.expiry_time),
             _iso(result.resolved_at), result.broker_order_id,
             result.resolution_source.value if result.resolution_source else "unresolved",
             result.data_source.value if result.data_source else "unknown")
        )
        conn.commit()

    def get_trade_results(self, asset: Optional[str] = None,
                          strategy: Optional[str] = None,
                          limit: int = 1000,
                          evidence_only: bool = True) -> list[TradeResult]:
        """Devuelve resultados de operaciones.

        Por defecto solo devuelve evidencia real (resuelta contra precio observado).
        Pasar evidence_only=False únicamente para auditoría del histórico sintético.
        """
        conn = self.connect()
        parts = ["SELECT * FROM trade_results"]
        where = []
        params = []
        if asset:
            where.append("asset=?")
            params.append(asset)
        if strategy:
            where.append("strategy=?")
            params.append(strategy)
        if evidence_only:
            where.append(EVIDENCE_SQL)
        if where:
            parts.append("WHERE " + " AND ".join(where))
        parts.append("ORDER BY timestamp DESC LIMIT ?")
        params.append(limit)
        rows = conn.execute(" ".join(parts), params).fetchall()
        result = []
        for r in rows:
            result.append(TradeResult(
                timestamp=datetime.fromisoformat(r["timestamp"]),
                asset=r["asset"],
                direction=Direction(r["direction"]),
                strategy=r["strategy"],
                expiry=r["expiry"], payout=r["payout"],
                stake=r["stake"], result=r["result"],
                execution_state=ExecutionState(r["execution_state"]),
                market_regime=MarketRegime(_col(r, "market_regime", "unknown")),
                confidence=_col(r, "confidence", 0.0),
                entry_timing=EntryTiming(_col(r, "entry_timing", "no_trade")),
                features=json.loads(_col(r, "features", "{}")),
                error=_col(r, "error"),
                entry_price=_col(r, "entry_price"),
                exit_price=_col(r, "exit_price"),
                entry_time=_parse_dt(_col(r, "entry_time")),
                expiry_time=_parse_dt(_col(r, "expiry_time")),
                resolved_at=_parse_dt(_col(r, "resolved_at")),
                broker_order_id=_col(r, "broker_order_id"),
                resolution_source=ResolutionSource(_col(r, "resolution_source", "unresolved")),
                data_source=DataSource(_col(r, "data_source", "unknown")),
            ))
        return result

    # --- Account ---

    def save_account_snapshot(self, snap: AccountSnapshot):
        conn = self.connect()
        conn.execute(
            """INSERT INTO account_snapshots
               (timestamp, mode, equity, balance, daily_pnl, daily_drawdown,
                open_positions, total_trades_today)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (snap.timestamp.isoformat(), snap.mode.value, snap.equity,
             snap.balance, snap.daily_pnl, snap.daily_drawdown,
             snap.open_positions, snap.total_trades_today)
        )
        conn.commit()

    def save_market_regime_snapshot(self, snap: MarketRegimeSnapshot):
        conn = self.connect()
        conn.execute(
            """INSERT INTO market_regime_snapshots
               (timestamp, asset, regime, adx, atr_percentile, ema_slope,
                price_distance_ema, features)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (snap.timestamp.isoformat(), snap.asset, snap.regime.value,
             snap.adx, snap.atr_percentile, snap.ema_slope,
             snap.price_distance_ema, json.dumps(snap.features, default=str))
        )
        conn.commit()

    def save_multi_timeframe_snapshot(self, snap: MultiTimeframeSnapshot):
        conn = self.connect()
        conn.execute(
            """INSERT INTO multi_timeframe_snapshots
               (timestamp, asset, m15_regime, m5_regime, m1_regime,
                alignment, m15_trend, m5_trend, m1_trend)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (snap.timestamp.isoformat(), snap.asset,
             snap.m15_regime.value, snap.m5_regime.value, snap.m1_regime.value,
             snap.alignment, snap.m15_trend, snap.m5_trend, snap.m1_trend)
        )
        conn.commit()

    # --- Errors ---

    def log_error(self, source: str, message: str, traceback: str = "",
                  level: str = "ERROR"):
        conn = self.connect()
        conn.execute(
            """INSERT INTO errors (timestamp, source, level, message, traceback)
               VALUES (?, ?, ?, ?, ?)""",
            (datetime.utcnow().isoformat(), source, level, message, traceback)
        )
        conn.commit()

    # --- Historical Edge ---

    def get_global_stats(self) -> dict:
        """Estadísticas globales de edge sobre toda la evidencia real.

        A diferencia de get_historical_edge (filtrado), este agrega todos los
        trade_results con resolución broker/candle. Sirve de punto de entrada
        para el supervisor IA.
        """
        conn = self.connect()
        rows = conn.execute(
            f"SELECT result, payout, execution_state FROM trade_results "
            f"WHERE execution_state IN ('won','lost') AND {EVIDENCE_SQL}"
        ).fetchall()
        total = len(rows)
        if total == 0:
            return {"total": 0, "wins": 0, "losses": 0, "win_rate": 0,
                    "profit_factor": 0, "avg_payout": 0, "expectancy": 0,
                    "total_pnl": 0}

        wins = sum(1 for r in rows if r["execution_state"] == "won")
        losses = total - wins
        win_rate = wins / total
        payouts = [r["payout"] for r in rows if r["payout"]]
        avg_payout = sum(payouts) / len(payouts) if payouts else 0
        total_pnl = sum(r["result"] for r in rows if r["result"] is not None)
        expectancy = win_rate * avg_payout - (1 - win_rate) if avg_payout else 0
        profit_factor = (wins * avg_payout) / losses if losses > 0 else float("inf")

        # Rachas (sobre orden temporal).
        ordered = conn.execute(
            f"SELECT execution_state FROM trade_results "
            f"WHERE execution_state IN ('won','lost') AND {EVIDENCE_SQL} "
            f"ORDER BY id"
        ).fetchall()
        cur_streak = max_streak = 0
        for r in ordered:
            if r["execution_state"] == "won":
                cur_streak = max(cur_streak, 0) + 1
                max_streak = max(max_streak, cur_streak)
            else:
                cur_streak = min(cur_streak, 0) - 1
        max_win_streak = max_streak
        max_loss_streak = -cur_streak if cur_streak < 0 else 0

        return {
            "total": total, "wins": wins, "losses": losses,
            "win_rate": round(win_rate, 4),
            "profit_factor": round(profit_factor, 4),
            "avg_payout": round(avg_payout, 4),
            "expectancy": round(expectancy, 4),
            "total_pnl": round(total_pnl, 2),
            "max_win_streak": max_win_streak,
            "max_loss_streak": max_loss_streak,
        }

    def get_historical_edge(self, asset: str, strategy: str, direction: Direction,
                            market_regime: MarketRegime, expiry: int,
                            payout: Optional[float] = None) -> dict:
        """Edge historico de un setup, calculado SOLO sobre evidencia real.

        Devuelve el resumen binomial completo (ver `app.stats.summarize_binomial`):
        win rate puntual Y su intervalo de Wilson, expectancy puntual Y su cota
        inferior, profit factor, p-valor contra el break-even y los dos flags
        `edge_proven` / `no_edge_proven`.

        DOS BUGS CORREGIDOS AQUI:

        1. NameError. La version anterior terminaba llamando a
           `wilson_lower_bound()`, funcion que no existia en ningun archivo de
           `app/`. Es decir: `get_historical_edge()` se rompia exactamente
           cuando ya habia muestra que consultar. Ahora se importa de
           `app.stats.core`.

        2. Se devolvia el win rate PUNTUAL como cifra principal y el
           `EdgeValidatorAgent` decidia con el. Un 66.7% sobre n=9 tiene IC de
           Wilson [35%, 88%]: no dice nada. `edge_proven` exige que la cota
           INFERIOR supere el break-even, no que lo supere la media muestral.

        Con n=0 se devuelve win_rate=None, no 0.0. "Sin muestra" no es
        "0% de edge"; confundirlos lleva a operar setups de los que no se sabe
        nada, o a retirarlos por no tener datos.
        """
        conn = self.connect()
        rows = conn.execute(
            f"""SELECT result, payout FROM trade_results
               WHERE asset=? AND strategy=? AND direction=?
               AND market_regime=? AND expiry=?
               AND execution_state IN ('won', 'lost')
               AND {EVIDENCE_SQL}""",
            (asset, strategy, direction.value, market_regime.value, expiry)
        ).fetchall()

        total = len(rows)
        wins = sum(1 for r in rows if (r["result"] or 0) > 0)
        payouts = [r["payout"] for r in rows if r["payout"]]
        avg_payout = (sum(payouts) / len(payouts)) if payouts else None
        effective_payout = avg_payout if avg_payout else (payout or 0.0)

        summary = summarize_binomial(wins, total, effective_payout)
        summary["avg_payout"] = round(avg_payout, 4) if avg_payout else None
        summary["payout_source"] = "observed" if avg_payout else "assumed"
        if summary["win_rate"] is not None:
            summary["win_rate"] = round(summary["win_rate"], 4)
        for k in ("win_rate_lower", "win_rate_upper", "expectancy",
                  "expectancy_lower", "break_even"):
            if summary.get(k) is not None:
                summary[k] = round(summary[k], 4)
        if summary.get("profit_factor") not in (None, float("inf")):
            summary["profit_factor"] = round(summary["profit_factor"], 4)
        return summary

    def get_edge_buckets(self, strategy: Optional[str] = None,
                         min_n: int = 1) -> list[dict]:
        """Todos los buckets de setup con muestra >= min_n, para el motor de mejora.

        Es la consulta que alimenta el analisis de comparaciones multiples:
        sin ver TODA la familia a la vez no se puede aplicar Benjamini-Hochberg,
        y sin BH el motor asciende al mejor de 40 ruidos.
        """
        conn = self.connect()
        params: list = []
        sql = (f"""SELECT asset, strategy, direction, market_regime, expiry,
                          COUNT(*) AS n,
                          SUM(CASE WHEN result > 0 THEN 1 ELSE 0 END) AS wins,
                          AVG(payout) AS avg_payout
                   FROM trade_results
                   WHERE execution_state IN ('won','lost') AND {EVIDENCE_SQL}""")
        if strategy:
            sql += " AND strategy=?"
            params.append(strategy)
        sql += """ GROUP BY asset, strategy, direction, market_regime, expiry
                   HAVING n >= ? ORDER BY n DESC"""
        params.append(min_n)
        out = []
        for r in conn.execute(sql, params).fetchall():
            payout = r["avg_payout"] or 0.85
            summ = summarize_binomial(r["wins"] or 0, r["n"], payout)
            summ.update({
                "asset": r["asset"], "strategy": r["strategy"],
                "direction": r["direction"], "market_regime": r["market_regime"],
                "expiry": r["expiry"],
                "slug": f"{r['asset']}|{r['strategy']}|{r['direction']}|"
                        f"{r['market_regime']}|{r['expiry']}",
            })
            out.append(summ)
        return out

    # ── Ciclo de vida de setups ───────────────────────────────────────────

    def upsert_setup(self, rec: SetupRecord, params: Optional[dict] = None):
        conn = self.connect()
        conn.execute(
            """INSERT INTO setups
               (slug, asset, strategy, direction, market_regime, expiry, state,
                verdict, n, n_traded, wins, win_rate, win_rate_lower, win_rate_upper,
                avg_payout, break_even, expectancy, expectancy_lower, looks,
                next_checkpoint, reopened, variants, stake_multiplier, params,
                updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(slug) DO UPDATE SET
                 state=excluded.state, verdict=excluded.verdict, n=excluded.n,
                 n_traded=excluded.n_traded,
                 wins=excluded.wins, win_rate=excluded.win_rate,
                 win_rate_lower=excluded.win_rate_lower,
                 win_rate_upper=excluded.win_rate_upper,
                 avg_payout=excluded.avg_payout, break_even=excluded.break_even,
                 expectancy=excluded.expectancy,
                 expectancy_lower=excluded.expectancy_lower,
                 looks=excluded.looks, next_checkpoint=excluded.next_checkpoint,
                 reopened=excluded.reopened, variants=excluded.variants,
                 stake_multiplier=excluded.stake_multiplier,
                 params=excluded.params, updated_at=excluded.updated_at""",
            (rec.key.slug, rec.key.asset, rec.key.strategy,
             rec.key.direction.value, rec.key.market_regime.value, rec.key.expiry,
             rec.state.value, rec.verdict.value, rec.n, rec.n_traded, rec.wins,
             rec.win_rate, rec.win_rate_lower, rec.win_rate_upper,
             rec.avg_payout, rec.break_even, rec.expectancy, rec.expectancy_lower,
             rec.looks, rec.next_checkpoint, rec.reopened, rec.variants,
             rec.stake_multiplier, json.dumps(params or {}, default=str),
             _iso(rec.updated_at))
        )
        conn.commit()

    def _row_to_setup(self, r) -> SetupRecord:
        return SetupRecord(
            key=SetupKey(r["asset"], r["strategy"], Direction(r["direction"]),
                         MarketRegime(r["market_regime"]), r["expiry"]),
            state=SetupState(r["state"]),
            verdict=SetupVerdict(r["verdict"]),
            n=r["n"] or 0, n_traded=_col(r, "n_traded", 0) or 0, wins=r["wins"] or 0,
            win_rate=_col(r, "win_rate"),
            win_rate_lower=_col(r, "win_rate_lower"),
            win_rate_upper=_col(r, "win_rate_upper"),
            avg_payout=_col(r, "avg_payout", 0.85),
            break_even=_col(r, "break_even"),
            expectancy=_col(r, "expectancy"),
            expectancy_lower=_col(r, "expectancy_lower"),
            looks=r["looks"] or 0,
            next_checkpoint=r["next_checkpoint"] or 0,
            reopened=r["reopened"] or 0,
            variants=r["variants"] or 0,
            stake_multiplier=_col(r, "stake_multiplier", 1.0),
            updated_at=_parse_dt(_col(r, "updated_at")),
        )

    def get_setup(self, key: SetupKey) -> Optional[SetupRecord]:
        conn = self.connect()
        r = conn.execute("SELECT * FROM setups WHERE slug=?", (key.slug,)).fetchone()
        return self._row_to_setup(r) if r else None

    def list_setups(self, state: Optional[SetupState] = None,
                    strategy: Optional[str] = None,
                    limit: int = 500) -> list[SetupRecord]:
        conn = self.connect()
        where, params = [], []
        if state:
            where.append("state=?"); params.append(state.value)
        if strategy:
            where.append("strategy=?"); params.append(strategy)
        sql = "SELECT * FROM setups"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY n DESC LIMIT ?"
        params.append(limit)
        return [self._row_to_setup(r) for r in conn.execute(sql, params).fetchall()]

    # ── Propuestas de mejora ──────────────────────────────────────────────

    # ── Forense de perdidas ───────────────────────────────────────────────

    def save_forensic_report(self, report) -> int:
        """Guarda el diagnostico de una operacion. Devuelve el id."""
        conn = self.connect()
        cursor = conn.execute(
            """INSERT INTO trade_forensics
               (trade_id, analysed_at, asset, strategy, direction, setup_slug,
                expiry, won, failure_mode, tags, excursions, rule,
                actionable_hint, diagnosis_confidence, features_at_entry,
                is_evidence, data_source)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (report.trade_id,
             report.analysed_at.isoformat() if report.analysed_at else None,
             report.asset, report.strategy, report.direction, report.setup_slug,
             report.expiry, None if report.won is None else int(report.won),
             report.mode.value, json.dumps(report.tags, default=str),
             json.dumps(report.excursions, default=str), report.rule,
             report.actionable_hint, report.confidence_in_diagnosis,
             json.dumps(report.features_at_entry, default=str),
             int(bool(report.is_evidence)), report.data_source),
        )
        conn.commit()
        return int(cursor.lastrowid or 0)

    def list_forensics(self, setup_slug: Optional[str] = None,
                       failure_mode: Optional[str] = None,
                       losses_only: bool = True,
                       limit: int = 500) -> list[dict]:
        """Diagnosticos guardados, para el digest y el supervisor de IA."""
        conn = self.connect()
        where, params = [], []
        if setup_slug:
            where.append("setup_slug=?"); params.append(setup_slug)
        if failure_mode:
            where.append("failure_mode=?"); params.append(failure_mode)
        if losses_only:
            where.append("won=0")
        sql = "SELECT * FROM trade_forensics"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            for key in ("tags", "excursions", "features_at_entry"):
                try:
                    d[key] = json.loads(d.get(key) or "{}" if key == "excursions"
                                        else d.get(key) or "[]")
                except json.JSONDecodeError:
                    d[key] = {} if key == "excursions" else []
            out.append(d)
        return out

    def forensic_mode_counts(self, min_n: int = 1) -> dict:
        """Cuantas perdidas por modo de fallo. Lo que responde 'donde duele'."""
        conn = self.connect()
        rows = conn.execute(
            """SELECT failure_mode, COUNT(*) AS n,
                      SUM(CASE WHEN is_evidence=1 THEN 1 ELSE 0 END) AS evidencia
               FROM trade_forensics WHERE won=0
               GROUP BY failure_mode ORDER BY n DESC""").fetchall()
        return {r["failure_mode"]: {"n": int(r["n"]), "evidencia": int(r["evidencia"] or 0),
                                    "solido": int(r["n"]) >= min_n}
                for r in rows if int(r["n"]) >= 1}

    def save_proposal(self, prop: ImprovementProposal):
        conn = self.connect()
        conn.execute(
            """INSERT INTO improvement_proposals
               (id, origin, target, action, payload, rationale, evidence, status,
                created_at, decided_at, rejection_reason, baseline_metric,
                candidate_metric, improvement)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET
                 status=excluded.status, decided_at=excluded.decided_at,
                 rejection_reason=excluded.rejection_reason,
                 baseline_metric=excluded.baseline_metric,
                 candidate_metric=excluded.candidate_metric,
                 improvement=excluded.improvement,
                 evidence=excluded.evidence""",
            (prop.id, prop.origin, prop.target, prop.action,
             json.dumps(prop.payload, default=str), prop.rationale,
             json.dumps(prop.evidence, default=str), prop.status,
             _iso(prop.created_at), _iso(prop.decided_at), prop.rejection_reason,
             prop.baseline_metric, prop.candidate_metric, prop.improvement)
        )
        conn.commit()

    def list_proposals(self, status: Optional[str] = None,
                       limit: int = 200) -> list[dict]:
        conn = self.connect()
        sql = "SELECT * FROM improvement_proposals"
        params: list = []
        if status:
            sql += " WHERE status=?"
            params.append(status)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        out = []
        for r in conn.execute(sql, params).fetchall():
            d = dict(r)
            d["payload"] = json.loads(d.get("payload") or "{}")
            d["evidence"] = json.loads(d.get("evidence") or "{}")
            out.append(d)
        return out

    # ── Backtests persistidos ─────────────────────────────────────────────

    def save_backtest_run(self, run: BacktestRun):
        conn = self.connect()
        conn.execute(
            """INSERT OR REPLACE INTO backtest_runs
               (id, created_at, label, data_source, asset, strategy, candles_used,
                params, in_sample, out_of_sample, walk_forward, verdict, honest_note)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (run.id, run.created_at.isoformat(), run.label, run.data_source.value,
             run.asset, run.strategy, run.candles_used,
             json.dumps(run.params, default=str),
             json.dumps(run.in_sample, default=str),
             json.dumps(run.out_of_sample, default=str),
             json.dumps(run.walk_forward, default=str),
             run.verdict, run.honest_note)
        )
        conn.commit()

    def list_backtest_runs(self, limit: int = 50) -> list[dict]:
        conn = self.connect()
        out = []
        for r in conn.execute(
            "SELECT * FROM backtest_runs ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall():
            d = dict(r)
            for k in ("params", "in_sample", "out_of_sample", "walk_forward"):
                d[k] = json.loads(d.get(k) or "{}")
            out.append(d)
        return out

    # ── IA aprendizaje supervisado ────────────────────────────────────────

    def audit_log(self, cycle_id: int, agent: str, event: str, detail: str = ""):
        conn = self.connect()
        conn.execute(
            "INSERT INTO ai_audit(cycle_id, agent, event, detail) VALUES (?,?,?,?)",
            (cycle_id, agent, event, detail),
        )
        conn.commit()
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    def get_audit_log(self, limit: int = 100):
        conn = self.connect()
        rows = conn.execute(
            "SELECT id, cycle_id, agent, event, detail, timestamp "
            "FROM ai_audit ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def next_cycle_id(self) -> int:
        conn = self.connect()
        row = conn.execute("SELECT COALESCE(MAX(cycle_id), 0) FROM ai_audit").fetchone()
        return int(row[0]) + 1

    def add_recommendation(self, cycle_id: int, agent: str, category: str,
                           recommendation: str, proposed_config_change: str = "",
                           severity: str = "info", evidence: str = "") -> int:
        conn = self.connect()
        cur = conn.execute(
            "INSERT INTO ai_recommendations(cycle_id, agent, category, severity, "
            "recommendation, proposed_config_change, evidence) "
            "VALUES (?,?,?,?,?,?,?)",
            (cycle_id, agent, category, severity, recommendation,
             proposed_config_change, evidence),
        )
        conn.commit()
        return int(cur.lastrowid)

    def get_recommendations(self, status: str = "pending", limit: int = 100):
        conn = self.connect()
        rows = conn.execute(
            "SELECT id, cycle_id, agent, category, severity, recommendation, "
            "proposed_config_change, status, created_at, applied_at, "
            "rejected_reason, evidence "
            "FROM ai_recommendations WHERE status=? ORDER BY id DESC LIMIT ?",
            (status, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def update_recommendation_status(self, rec_id: int, status: str,
                                     reason: str = ""):
        conn = self.connect()
        if status == "applied":
            conn.execute(
                "UPDATE ai_recommendations SET status='applied', "
                "applied_at=datetime('now') WHERE id=?", (rec_id,)
            )
        elif status == "rejected":
            conn.execute(
                "UPDATE ai_recommendations SET status='rejected', "
                "rejected_reason=? WHERE id=?", (reason, rec_id)
            )
        else:
            conn.execute(
                "UPDATE ai_recommendations SET status=? WHERE id=?",
                (status, rec_id)
            )
        conn.commit()

    def add_overnight_report(self, run_date: str, summary: str,
                             metrics: str = "", recommendations: str = "",
                             model: str = "", tokens_used: int = 0,
                             duration_sec: float = 0.0) -> int:
        conn = self.connect()
        cur = conn.execute(
            "INSERT INTO ai_overnight(run_date, summary, metrics, recommendations, "
            "model, tokens_used, duration_sec) VALUES (?,?,?,?,?,?,?)",
            (run_date, summary, metrics, recommendations, model,
             tokens_used, duration_sec),
        )
        conn.commit()
        return int(cur.lastrowid)


repository = Repository()
