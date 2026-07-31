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
    TradingMode, EntryTiming, BacktestResult, ResolutionSource
)

# Solo estas fuentes de resolución cuentan como evidencia estadística.
# Las operaciones simuladas o sin resolver quedan fuera de todo cálculo de edge.
EVIDENCE_SQL = "resolution_source IN ('broker', 'candle')"


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
                resolution_source TEXT DEFAULT 'unresolved'
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
        }
        added = [name for name in new_columns if name not in existing]
        for name in added:
            conn.execute(f"ALTER TABLE trade_results ADD COLUMN {name} {new_columns[name]}")

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
               (asset, timeframe, open_time, open, high, low, close, volume, source, quality)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (candle.asset, candle.timeframe.value, candle.open_time.isoformat(),
             candle.open, candle.high, candle.low, candle.close,
             candle.volume, candle.source, candle.quality.value)
        )
        conn.commit()

    def save_candles(self, candles: list[Candle]):
        conn = self.connect()
        for c in candles:
            conn.execute(
                """INSERT OR REPLACE INTO candles
                   (asset, timeframe, open_time, open, high, low, close, volume, source, quality)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (c.asset, c.timeframe.value, c.open_time.isoformat(),
                 c.open, c.high, c.low, c.close,
                 c.volume, c.source, c.quality.value)
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
                volume=r.get("volume"), source=r.get("source", "unknown")
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
             signal.invalidation, json.dumps(signal.features),
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
             json.dumps(decision.edge_details or {}),
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
                resolved_at, broker_order_id, resolution_source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
             result.resolution_source.value if result.resolution_source else "unresolved")
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
             snap.price_distance_ema, json.dumps(snap.features))
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
                            market_regime: MarketRegime, expiry: int) -> dict:
        """Edge histórico calculado SOLO sobre evidencia real.

        Devuelve tanto el win rate puntual como su cota inferior de Wilson al 95%.
        El gate de ejecución debe usar la cota inferior: con muestras pequeñas el
        win rate puntual sobreestima sistemáticamente el edge.
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
        if total == 0:
            return {"total": 0, "win_rate": 0, "win_rate_lower_95": 0, "expectancy": 0}

        wins = sum(1 for r in rows if r["result"] > 0)
        losses = total - wins
        win_rate = wins / total
        payouts = [r["payout"] for r in rows if r["payout"]]
        avg_payout = sum(payouts) / len(payouts) if payouts else None

        if not avg_payout:
            return {"total": total, "win_rate": win_rate,
                    "win_rate_lower_95": 0, "expectancy": 0}

        wr_lower = wilson_lower_bound(wins, total)
        expectancy = win_rate * avg_payout - (1 - win_rate)
        expectancy_lower = wr_lower * avg_payout - (1 - wr_lower)
        profit_factor = (wins * avg_payout) / losses if losses > 0 else float("inf")

        return {
            "total": total,
            "wins": wins,
            "losses": losses,
            "win_rate": round(win_rate, 4),
            "win_rate_lower_95": round(wr_lower, 4),
            "expectancy": round(expectancy, 4),
            "expectancy_lower_95": round(expectancy_lower, 4),
            "profit_factor": round(profit_factor, 4),
            "avg_payout": round(avg_payout, 4),
            "break_even_wr": round(1 / (1 + avg_payout), 4) if avg_payout > 0 else 0,
        }

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
