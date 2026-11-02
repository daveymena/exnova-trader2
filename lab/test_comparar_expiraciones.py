import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from comparar_expiraciones import compare


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        t = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.rows = [(t+timedelta(seconds=10*i), 10, 12, 9, 11) for i in range(400)]

    def test_no_boundary_crossing_and_actual_horizons(self):
        def signal(rows):
            return {'direction': 'CALL', 'signal_time': rows[-1][0].isoformat()}
        with patch('comparar_expiraciones.latest_signal', signal):
            result = compare(self.rows, .85)
        for e in result['events']:
            entry = datetime.fromisoformat(e['entry_time'])
            boundary = datetime.fromisoformat(result['split_time'])
            self.assertFalse(entry < boundary < entry+timedelta(seconds=300))
            self.assertEqual(e['outcomes']['180'], 'win')
        self.assertTrue(result['summary']['holdout']['180']['samples'])

    def test_rejects_gaps_and_invalid_payout(self):
        with self.assertRaises(ValueError): compare(self.rows[:-1], float('nan'))
        with self.assertRaises(ValueError): compare(self.rows[:250]+self.rows[251:], .85)


if __name__ == '__main__':
    unittest.main()
