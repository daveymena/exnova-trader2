import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from graficos_mercado import save_chart


class ChartTest(unittest.TestCase):
    def test_chart_is_registered_and_safely_named(self):
        t = datetime(2026, 1, 1, tzinfo=timezone.utc)
        rows = [(t + timedelta(seconds=10*i), 10, 11, 9, 10.5) for i in range(230)]
        with tempfile.TemporaryDirectory() as d:
            db = str(Path(d)/'test.db')
            path = save_chart(db, d, '../../EURUSD', rows)
            self.assertEqual(path.parent, Path(d))
            self.assertEqual(path.read_bytes()[:8], b'\x89PNG\r\n\x1a\n')
            with sqlite3.connect(db) as conn:
                self.assertEqual(conn.execute('SELECT count(*) FROM research_chart_snapshots').fetchone()[0], 1)


if __name__ == '__main__':
    unittest.main()
