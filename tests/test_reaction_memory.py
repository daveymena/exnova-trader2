import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta

from app.data.schemas import Candle, Timeframe
from app.research.reaction_memory import observe


class ReactionMemoryTest(unittest.TestCase):
    def test_causal_contact_and_unresolved_gap(self):
        start = datetime(2026, 1, 1)
        bars = [Candle('EURUSD-OTC', Timeframe.M1, start + timedelta(minutes=i),
                       10, 11, 9, 10, source='exnova') for i in range(30)]
        bars.append(Candle('EURUSD-OTC', Timeframe.M1, start + timedelta(minutes=30),
                           9.5, 10, 8.9, 9.7, source='exnova'))
        with tempfile.NamedTemporaryFile() as f:
            observe(f.name, bars)
            with sqlite3.connect(f.name) as db:
                row = db.execute('SELECT level, outcome_60, features FROM reaction_observations').fetchone()
            self.assertEqual(row[0], 9)
            self.assertIsNone(row[1])
            self.assertEqual(json.loads(row[2])['level_lookback_minutes'], 30)
            bars.append(Candle('EURUSD-OTC', Timeframe.M1, start + timedelta(minutes=31),
                               9.7, 10.3, 9.6, 10.1, source='exnova'))
            observe(f.name, bars)
            observe(f.name, bars)
            with sqlite3.connect(f.name) as db:
                result = db.execute('SELECT outcome_60, outcome_120 FROM reaction_observations '
                                    'WHERE contact_time=? AND side=?', (bars[30].open_time.isoformat(), 'support')).fetchone()
                count = db.execute('SELECT count(*) FROM reaction_observations WHERE contact_time=?',
                                   (bars[30].open_time.isoformat(),)).fetchone()[0]
            self.assertEqual(result, ('win', None))
            self.assertEqual(count, 1)


if __name__ == '__main__':
    unittest.main()
