import csv
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from retroceso_lab import analyze, read_candles

class LabTests(unittest.TestCase):
    def make_file(self, gap=False):
        f=tempfile.NamedTemporaryFile(mode='w',newline='',delete=False)
        self.addCleanup(lambda: os.unlink(f.name))
        w=csv.writer(f); w.writerow(['timestamp','open','high','low','close'])
        t=datetime(2026,1,1,tzinfo=timezone.utc)
        for i in range(245):
            w.writerow([(t+timedelta(seconds=i*10+(10 if gap and i>=100 else 0))).isoformat(),100,101,99,100])
        f.close(); return f.name
    def test_rejects_gap(self):
        with self.assertRaises(ValueError): read_candles(self.make_file(True))
    def test_flat_market_has_no_trade(self):
        r=analyze(read_candles(self.make_file()),0.85)
        self.assertEqual(r['signals'],0)
        self.assertIsNone(r['win_rate_excluding_ties'])
    def test_future_prices_do_not_change_previous_signal(self):
        rows=read_candles(self.make_file())
        a=analyze(rows,0.85)
        rows[-1]=(rows[-1][0],100,110,90,105)
        b=analyze(rows,0.85)
        self.assertEqual(a['signals'],b['signals'])

if __name__=='__main__': unittest.main()

class StructureTests(unittest.TestCase):
    def candles(self, lows, highs=None):
        highs=highs or [v+2 for v in lows]
        return [(None, 0, h, l, 0) for l,h in zip(lows,highs)]
    def test_confirmed_higher_lows(self):
        from retroceso_lab import structure_pivots
        self.assertTrue(structure_pivots(self.candles([5,4,2,4,5,6,5,3,5,6]),1,width=1))
    def test_unconfirmed_last_pivot_is_not_used(self):
        from retroceso_lab import structure_pivots
        self.assertFalse(structure_pivots(self.candles([5,4,2,4,5,6,5,3]),1,width=1))
    def test_lower_highs(self):
        from retroceso_lab import structure_pivots
        self.assertTrue(structure_pivots(self.candles([0]*10,[5,6,9,6,5,4,5,8,5,4]),-1,width=1))
