"""Compara vencimientos sobre señales históricas, sin enviar órdenes."""
import argparse
import json
import math
from datetime import timedelta

from retroceso_lab import latest_signal, read_candles

EXPIRIES = (60, 120, 180, 300)


def summarize(events, expiry, payout):
    outcomes = [e['outcomes'][str(expiry)] for e in events]
    wins, losses, ties = (outcomes.count(x) for x in ('win', 'loss', 'tie'))
    total = len(outcomes)
    return {'samples': total, 'wins': wins, 'losses': losses, 'ties': ties,
            'win_rate_excluding_ties': wins/(wins+losses) if wins+losses else None,
            'pnl_units_assuming_tie_refund': round(wins*payout-losses, 4),
            'payout_assumption': payout}


def compare(rows, payout, split_fraction=0.7):
    if not math.isfinite(payout) or not 0 < payout <= 1:
        raise ValueError('payout debe estar entre 0 y 1')
    if not 0.5 <= split_fraction < 1:
        raise ValueError('split debe estar entre 0.5 y 1')
    if any((b[0]-a[0]).total_seconds() != 10 for a, b in zip(rows, rows[1:])):
        raise ValueError('velas discontinuas o desordenadas')
    # The split is fixed before signals are evaluated. Exclude trades whose
    # longest expiry crosses the boundary; no selection on the final sample.
    boundary = int(len(rows)*split_fraction)
    events = []
    for i in range(220, len(rows)-30):
        if i+1 < boundary <= i+30:
            continue
        signal = latest_signal(rows[:i+1])
        if signal is None:
            continue
        entry = rows[i+1][1]
        direction = 1 if signal['direction'] == 'CALL' else -1
        outcomes = {}
        for seconds in EXPIRIES:
            end = rows[i + seconds//10][4]
            delta = direction*(end-entry)
            outcomes[str(seconds)] = 'win' if delta > 0 else 'loss' if delta < 0 else 'tie'
        events.append({**signal, 'sample': 'development' if i+30 < boundary else 'holdout',
                       'entry_reference': entry, 'entry_time': rows[i+1][0].isoformat(),
                       'outcomes': outcomes})
    groups = {name: [e for e in events if e['sample']==name]
              for name in ('development', 'holdout')}
    return {'split_time': rows[boundary][0].isoformat(), 'expiries_seconds': EXPIRIES,
            'summary': {name: {str(s): summarize(group, s, payout) for s in EXPIRIES}
                        for name, group in groups.items()},
            'events': events,
            'limitations': 'Cierres OHLC hipotéticos, no precios ni liquidaciones del broker; '
                           'sin latencia, payout histórico ni ejecución. Señales solapadas; '
                           'no seleccionar ni afirmar ventaja sin validación independiente.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('csv')
    parser.add_argument('--payout', type=float, required=True)
    parser.add_argument('--split', type=float, default=0.7)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    result = compare(read_candles(args.csv), args.payout, args.split)
    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(json.dumps(result['summary'], ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
