import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from observador_exnova import save_rows


class ObserverTest(unittest.TestCase):
    def test_storage_is_idempotent_and_stores_only_one_signal(self):
        t = datetime(2026, 1, 1, tzinfo=timezone.utc)
        rows = [(t + timedelta(seconds=10*i), 10, 11, 9, 10) for i in range(230)]
        signal = {'direction': 'CALL', 'signal_time': (t+timedelta(seconds=2300)).isoformat()}
        with tempfile.NamedTemporaryFile() as f, patch('observador_exnova.latest_signal', return_value=signal):
            save_rows(f.name, 'EURUSD-OTC', rows)
            save_rows(f.name, 'EURUSD-OTC', rows)
            with sqlite3.connect(f.name) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM research_candles_10s').fetchone()[0], 230)
                self.assertEqual(db.execute('SELECT count(*) FROM research_signals_10s').fetchone()[0], 1)


if __name__ == '__main__':
    unittest.main()
