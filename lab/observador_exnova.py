"""Observador Exnova de solo lectura: guarda velas y señales sin operar."""
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from retroceso_lab import latest_signal
from seguir_retroceso import validated_rows
from app.services.exnova_broker import ExnovaBroker
from app.data.schemas import Timeframe
from app.research.reaction_memory import observe


def save_rows(db_path, asset, rows):
    with sqlite3.connect(db_path) as db:
        db.execute('CREATE TABLE IF NOT EXISTS research_candles_10s ('
                   'asset TEXT NOT NULL, open_time TEXT NOT NULL, open REAL NOT NULL, '
                   'high REAL NOT NULL, low REAL NOT NULL, close REAL NOT NULL, '
                   'PRIMARY KEY(asset,open_time))')
        db.executemany('INSERT OR IGNORE INTO research_candles_10s VALUES (?,?,?,?,?,?)',
                       [(asset, r[0].isoformat(), *r[1:]) for r in rows])
        db.execute('CREATE TABLE IF NOT EXISTS research_signals_10s ('
                   'asset TEXT NOT NULL, signal_time TEXT NOT NULL, data TEXT NOT NULL, '
                   'PRIMARY KEY(asset,signal_time))')
        signal = latest_signal(rows)
        if signal:
            db.execute('INSERT OR IGNORE INTO research_signals_10s VALUES (?,?,?)',
                       (asset, signal['signal_time'], json.dumps(signal, sort_keys=True)))
        return signal


def main():
    email, password = os.getenv('EXNOVA_EMAIL'), os.getenv('EXNOVA_PASSWORD')
    if not email or not password:
        raise SystemExit('Faltan EXNOVA_EMAIL y EXNOVA_PASSWORD en EasyPanel')
    assets = [a.strip() for a in os.getenv('RESEARCH_ASSETS', 'EURUSD-OTC').split(',') if a.strip()]
    if not assets:
        raise SystemExit('RESEARCH_ASSETS está vacío')
    db_path = os.getenv('RESEARCH_DATABASE_PATH', '/app/data/research.db')
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    broker = ExnovaBroker(email, password, account_type='PRACTICE')
    try:
        while True:
            try:
                if not broker.is_connected():
                    broker.disconnect()
                    if not broker.connect(max_retries=1):
                        print('[OBSERVADOR] Conexión no disponible; reintento en 30s', flush=True)
                        time.sleep(30)
                        continue
                for asset in assets:
                    try:
                        now = datetime.now(timezone.utc)
                        rows = validated_rows(broker.get_candles(asset, 10, 500), now)
                        signal = save_rows(db_path, asset, rows)
                        m1 = broker.get_candles_as_schema(asset, Timeframe.M1, 100)
                        # Exnova's adapter returns naive UTC timestamps.
                        closed = [c for c in m1 if c.open_time.replace(tzinfo=timezone.utc).timestamp()+60 <= time.time()]
                        observe(db_path, closed)
                        print(f'[OBSERVADOR] {asset} última 10s={rows[-1][0].isoformat()} '
                              f'señal={signal["direction"] if signal else "ninguna"}', flush=True)
                    except Exception as exc:
                        print(f'[OBSERVADOR] {asset}: datos no válidos ({type(exc).__name__}); '
                              'sin señal', flush=True)
                    time.sleep(2)
                time.sleep(8)
            except Exception as exc:
                print(f'[OBSERVADOR] Error {type(exc).__name__}; reintentando', flush=True)
                broker.disconnect()
                time.sleep(30)
    except KeyboardInterrupt:
        pass
    finally:
        broker.disconnect()


if __name__ == '__main__':
    main()
