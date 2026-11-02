"""Seguimiento local de señales IQ: solo lectura; no opera."""
import argparse
import json
import math
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from retroceso_lab import latest_signal
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))


def validated_rows(frame, now):
    if frame.empty: raise ValueError('IQ no devolvió velas')
    rows=[]
    for ts, x in frame.iterrows():
        t=ts.to_pydatetime()
        t=t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t.astimezone(timezone.utc)
        if t+timedelta(seconds=10)>now: continue
        o,h,l,c=(float(x[k]) for k in ('open','high','low','close'))
        if not all(math.isfinite(v) for v in (o,h,l,c)) or not 0<l<=min(o,c)<=max(o,c)<=h:
            raise ValueError('OHLC inválido')
        rows.append((t,o,h,l,c))
    rows.sort(key=lambda x:x[0])
    if len(rows)<221: raise ValueError('Historial insuficiente para EMA200')
    if any((b[0]-a[0]).total_seconds()!=10 for a,b in zip(rows,rows[1:])):
        raise ValueError('Velas duplicadas, discontinuas o distintas de 10 s')
    age=(now-(rows[-1][0]+timedelta(seconds=10))).total_seconds()
    if not 0<=age<=15: raise ValueError('Última vela obsoleta')
    return rows


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--asset',required=True); p.add_argument('--output',default='senales_retroceso.jsonl')
    args=p.parse_args()
    email=os.getenv('IQ_OPTION_EMAIL'); password=os.getenv('IQ_OPTION_PASSWORD')
    if not email or not password: p.error('Configura IQ_OPTION_EMAIL e IQ_OPTION_PASSWORD localmente')
    from app.services.iqoption_broker import IQOptionBroker
    broker=IQOptionBroker(email,password,account_type='PRACTICE')
    last=None
    try:
        if not broker.connect(max_retries=1): raise RuntimeError('No se pudo conectar a IQ Option')
        print('Seguimiento sin órdenes; Ctrl+C para detener.',flush=True)
        while True:
            try:
                now=datetime.now(timezone.utc)
                rows=validated_rows(broker.get_candles(args.asset,10,500),now)
                stamp=rows[-1][0]
                if stamp!=last:
                    last=stamp
                    signal=latest_signal(rows)
                    if signal:
                        record={'asset':args.asset,'mode':'signal_only','observed_at':now.isoformat(),**signal}
                        with open(args.output,'a',encoding='utf-8') as f: f.write(json.dumps(record,ensure_ascii=False)+'\n')
                        print(json.dumps(record,ensure_ascii=False),flush=True)
                    else: print(f'{stamp.isoformat()} Sin señal',flush=True)
            except Exception as exc:
                print(f'Datos no válidos; sin señal: {type(exc).__name__}: {exc}',file=sys.stderr,flush=True)
            time.sleep(2)
    except KeyboardInterrupt:
        print('\nSeguimiento detenido.')
    finally: broker.disconnect()

if __name__=='__main__': main()
