import unittest
from datetime import datetime, timedelta, timezone
import pandas as pd
from seguir_retroceso import validated_rows

class LiveDataTests(unittest.TestCase):
    def setUp(self):
        self.start=datetime(2026,1,1,tzinfo=timezone.utc)
        self.frame=pd.DataFrame([{'open':100,'high':102,'low':99,'close':101}]*222,index=pd.date_range(self.start,periods=222,freq='10s'))
    def test_open_bar_excluded(self):
        now=self.start+timedelta(seconds=2210)
        self.assertEqual(len(validated_rows(self.frame,now)),221)
    def test_stale_bar_rejected(self):
        with self.assertRaises(ValueError): validated_rows(self.frame,self.start+timedelta(seconds=2300))
    def test_missing_bar_rejected(self):
        frame=self.frame.drop(self.frame.index[3])
        with self.assertRaises(ValueError): validated_rows(frame,self.start+timedelta(seconds=2220))

if __name__=='__main__': unittest.main()
