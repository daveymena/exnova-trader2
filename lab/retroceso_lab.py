"""Laboratorio offline de retroceso a favor. No conecta ni envía órdenes."""
import argparse
import csv
import json
from datetime import datetime, timedelta, timezone


def read_candles(path):
    rows = []
    with open(path, newline='', encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            stamp = row['timestamp'].strip()
            try:
                t = datetime.fromtimestamp(float(stamp), timezone.utc)
            except ValueError:
                t = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
                if t.tzinfo is None:
                    raise ValueError('timestamp debe incluir zona horaria o ser Unix UTC')
                t = t.astimezone(timezone.utc)
            o,h,l,c = (float(row[k]) for k in ('open','high','low','close'))
            if not (0 < l <= min(o,c) <= max(o,c) <= h):
                raise ValueError('OHLC inválido: ' + stamp)
            rows.append((t,o,h,l,c))
    if any((b[0]-a[0]).total_seconds()!=10 for a,b in zip(rows,rows[1:])):
        raise ValueError('Las velas deben estar ordenadas, sin duplicados ni huecos de 10 segundos')
    if len(rows)<240: raise ValueError('Se requieren al menos 240 velas de 10 segundos')
    return rows


def ema(values, period):
    out=[values[0]]
    k=2/(period+1)
    for v in values[1:]: out.append(k*v+(1-k)*out[-1])
    return out


def structure_pivots(rows, direction, width=2, lookback=90):
    """Compare the two latest confirmed swings; no candles beyond rows are used."""
    points=[]
    for j in range(max(width, len(rows)-lookback), len(rows)-width):
        value=rows[j][3] if direction==1 else rows[j][2]
        neighbors=[rows[k][3] if direction==1 else rows[k][2]
                   for k in range(j-width,j+width+1) if k!=j]
        if (direction==1 and all(value < x for x in neighbors)) or (direction==-1 and all(value > x for x in neighbors)):
            points.append(value)
    return len(points)>=2 and direction*(points[-1]-points[-2])>0


def latest_signal(rows):
    """Evalúa únicamente velas cerradas; no necesita velas futuras."""
    if len(rows)<221:
        return None
    i=len(rows)-1
    closes=[x[4] for x in rows]
    e20,e50,e200=(ema(closes,n) for n in (20,50,200))
    tr=[rows[0][2]-rows[0][3]]
    for k in range(1,len(rows)):
        tr.append(max(rows[k][2]-rows[k][3],abs(rows[k][2]-closes[k-1]),abs(rows[k][3]-closes[k-1])))
    atr=ema(tr,14)
    a=atr[i]
    if a<=0: return None
    direction=1 if e20[i]>e50[i]>e200[i] else -1 if e20[i]<e50[i]<e200[i] else 0
    if not direction or direction*(e20[i]-e20[i-3]) < .03*a: return None
    if not structure_pivots(rows[:i+1], direction): return None
    # Recent EMA crossover and narrow 5-minute range.
    if any((e20[j]-e50[j])*(e20[j-1]-e50[j-1]) <= 0 for j in range(i-9,i+1)): return None
    if max(x[2] for x in rows[i-29:i+1])-min(x[3] for x in rows[i-29:i+1]) < 2*a: return None
    trigger=rows[i]; previous=rows[i-1]
    if direction*(trigger[4]-trigger[1])<=0: return None
    if direction==1 and trigger[4]<=previous[2]: return None
    if direction==-1 and trigger[4]>=previous[3]: return None
    # Consecutive countertrend candles, directly before trigger.
    j=i-1
    while j>=0 and i-j<=6 and direction*(rows[j][4]-rows[j][1])<0: j-=1
    pull=rows[j+1:i]
    if not 1<=len(pull)<=6: return None
    # Explicit operational approximation: prior 12 bars define impulse.
    start=max(0,j-11); prior=rows[start:j+1]
    if not prior: return None
    if direction==1:
        origin=min(x[3] for x in prior); peak=max(x[2] for x in prior)
        if next(k for k,x in enumerate(prior) if x[3]==origin) >= max(k for k,x in enumerate(prior) if x[2]==peak): return None
        depth=(peak-min(x[3] for x in pull))/(peak-origin) if peak>origin else 0
        touched=any(rows[k][3]-.35*atr[k]<=e20[k]<=rows[k][2]+.35*atr[k] for k in range(j+1,i))
        breach=any(rows[k][4]<e50[k] for k in range(j+1,i))
    else:
        origin=max(x[2] for x in prior); peak=min(x[3] for x in prior)
        if next(k for k,x in enumerate(prior) if x[2]==origin) >= max(k for k,x in enumerate(prior) if x[3]==peak): return None
        depth=(max(x[2] for x in pull)-peak)/(origin-peak) if origin>peak else 0
        touched=any(rows[k][3]-.35*atr[k]<=e20[k]<=rows[k][2]+.35*atr[k] for k in range(j+1,i))
        breach=any(rows[k][4]>e50[k] for k in range(j+1,i))
    magnitude=abs(peak-origin)
    impulse_bodies=[abs(x[4]-x[1]) for x in prior if direction*(x[4]-x[1])>0]
    if magnitude<1.2*a or not .2<=depth<=.75 or not touched or breach or not impulse_bodies: return None
    if sum(abs(x[4]-x[1]) for x in pull)/len(pull) > .85*sum(impulse_bodies)/len(impulse_bodies): return None
    if abs(trigger[4]-trigger[1])>2*a or abs(trigger[4]-e20[i])>2*a: return None
    return {'signal_time':(rows[i][0]+timedelta(seconds=10)).isoformat(), 'direction':'CALL' if direction==1 else 'PUT', 'expiry_seconds':180, 'atr':a, 'pullback_bars':len(pull), 'pullback_fraction':round(depth,4), 'impulse_atr':round(magnitude/a,4)}


def analyze(rows, payout):
    closes=[x[4] for x in rows]
    e20,e50,e200=(ema(closes,n) for n in (20,50,200))
    tr=[rows[0][2]-rows[0][3]]
    for i in range(1,len(rows)):
        tr.append(max(rows[i][2]-rows[i][3],abs(rows[i][2]-closes[i-1]),abs(rows[i][3]-closes[i-1])))
    atr=ema(tr,14)
    results=[]
    available=0
    consecutive_losses=0
    last_loss_direction=None
    last_loss_resolved=-100
    stopped=False
    for i in range(220,len(rows)-18):
        if i < available: continue
        candidate=latest_signal(rows[:i+1])
        if candidate is None: continue
        direction=1 if candidate['direction']=='CALL' else -1
        if last_loss_direction is not None and direction != last_loss_direction and i < last_loss_resolved+12: continue
        # Entry is next open; 18 complete 10s candles end at i+18.
        entry=rows[i+1][1]; exit_price=rows[i+18][4]
        delta=direction*(exit_price-entry)
        outcome='win' if delta>0 else 'loss' if delta<0 else 'tie'
        results.append({**candidate, 'entry':entry,'exit':exit_price,'outcome':outcome,'pnl_units':payout if delta>0 else -1 if delta<0 else 0})
        available=i+19+6  # one active position plus 6 bars cooling after expiry
        if outcome == 'loss':
            consecutive_losses+=1
            last_loss_direction=direction
            last_loss_resolved=i+18
            if consecutive_losses>=3:
                stopped=True
                break
        elif outcome == 'win':
            consecutive_losses=0
    wins=sum(x['outcome']=='win' for x in results); losses=sum(x['outcome']=='loss' for x in results)
    return {'stopped_after_three_losses':stopped,'signals':len(results),'wins':wins,'losses':losses,'ties':len(results)-wins-losses,'win_rate_excluding_ties':wins/(wins+losses) if wins+losses else None,'pnl_units':round(sum(x['pnl_units'] for x in results),4),'trades':results}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('csv'); p.add_argument('--payout',type=float,required=True); p.add_argument('--output',required=True)
    a=p.parse_args()
    if not 0<a.payout<=1: p.error('payout debe estar entre 0 y 1')
    report=analyze(read_candles(a.csv),a.payout)
    report.update({'source_file':a.csv,'payout_assumption':a.payout,'limitations':'Experimental: aproximación explícita, sin liquidación broker ni latencia; pivotes y filtros son aproximaciones experimentales.'})
    with open(a.output,'w',encoding='utf-8') as f: json.dump(report,f,indent=2,ensure_ascii=False)
    print(json.dumps({k:v for k,v in report.items() if k!='trades'},ensure_ascii=False,indent=2))

if __name__=='__main__': main()
