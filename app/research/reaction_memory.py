"""Observational, causal M1 reaction log. This module never places orders."""
import json
import sqlite3
from datetime import timedelta

from app.data.candle_validation import is_trusted_candle_source
from app.data.schemas import DataQuality, Timeframe


def observe(db_path, candles, payout=None):
    """Store level contacts and hypothetical subsequent candle-close outcomes.

    Levels are the extrema of the 30 completed candles preceding the contact.
    Outcomes use the contact close as a reference, not an executable quote.
    Missing candles leave outcomes unresolved. Results are research only.
    """
    rows = sorted(candles, key=lambda c: c.open_time)
    if len(rows) < 31:
        return
    if any(c.timeframe != Timeframe.M1 or not is_trusted_candle_source(c.source)
           or c.quality != DataQuality.NORMAL for c in rows):
        return
    asset = rows[-1].asset
    if any(c.asset != asset for c in rows):
        return
    by_time = {c.open_time: c for c in rows}
    with sqlite3.connect(db_path) as db:
        db.execute('''CREATE TABLE IF NOT EXISTS reaction_observations (
            asset TEXT NOT NULL, source TEXT NOT NULL, contact_time TEXT NOT NULL,
            side TEXT NOT NULL, level REAL NOT NULL, reference_close REAL NOT NULL,
            features TEXT NOT NULL, payout REAL,
            outcome_60 TEXT, outcome_120 TEXT, outcome_180 TEXT,
            PRIMARY KEY(asset, source, contact_time, side))''')
        # Each contact only uses bars available at that time; no future leakage.
        for i in range(30, len(rows)):
            history, bar = rows[i-30:i], rows[i]
            sequence = history + [bar]
            if any(b.open_time - a.open_time != timedelta(minutes=1)
                   for a, b in zip(sequence, sequence[1:])):
                continue
            support = min(c.low for c in history)
            resistance = max(c.high for c in history)
            features = json.dumps({'open': bar.open, 'high': bar.high, 'low': bar.low,
                                   'close': bar.close, 'body': bar.body,
                                   'lower_wick': bar.lower_wick, 'upper_wick': bar.upper_wick,
                                   'level_lookback_minutes': 30}, sort_keys=True)
            for side, level, hit in [('support', support, bar.low <= support <= bar.high),
                                     ('resistance', resistance, bar.low <= resistance <= bar.high)]:
                if not hit:
                    continue
                # Historical contacts must not be assigned the current payout.
                observed_payout = payout if i == len(rows)-1 and payout is not None and 0 < payout <= 1 else None
                db.execute('INSERT OR IGNORE INTO reaction_observations '
                           '(asset,source,contact_time,side,level,reference_close,features,payout) '
                           'VALUES (?,?,?,?,?,?,?,?)',
                           (asset, bar.source, bar.open_time.isoformat(), side, level,
                            bar.close, features, observed_payout))
        pending = db.execute('SELECT contact_time, side, reference_close, source FROM reaction_observations '
                             'WHERE asset=? AND (outcome_60 IS NULL OR outcome_120 IS NULL OR outcome_180 IS NULL)',
                             (asset,)).fetchall()
        for stamp, side, ref, source in pending:
            from datetime import datetime
            start = datetime.fromisoformat(stamp)
            outcomes = []
            for n in (1, 2, 3):
                future = [by_time.get(start + timedelta(minutes=k)) for k in range(1, n+1)]
                if any(c is None or c.source != source for c in future):
                    outcomes.append(None)
                    continue
                delta = (future[-1].close - ref) * (1 if side == 'support' else -1)
                outcomes.append('win' if delta > 0 else 'loss' if delta < 0 else 'tie')
            db.execute('UPDATE reaction_observations SET '
                       'outcome_60=COALESCE(outcome_60,?), outcome_120=COALESCE(outcome_120,?), '
                       'outcome_180=COALESCE(outcome_180,?) '
                       'WHERE asset=? AND source=? AND contact_time=? AND side=?',
                       (*outcomes, asset, source, stamp, side))
