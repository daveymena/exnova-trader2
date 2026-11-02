"""Genera imágenes locales a partir de las velas observadas; no envía órdenes."""
import hashlib
import json
import os
import re
import sqlite3
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from retroceso_lab import ema


def save_chart(db_path, chart_dir, asset, rows, signal=None, kind='periodico'):
    if not rows:
        raise ValueError('No hay velas para dibujar')
    chart_dir = Path(chart_dir)
    chart_dir.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r'[^A-Za-z0-9_-]', '_', asset)[:48]
    suffix = hashlib.sha256(asset.encode()).hexdigest()[:8]
    stamp = rows[-1][0].strftime('%Y%m%dT%H%M%SZ')
    path = chart_dir / f'{slug}_{suffix}_{stamp}.png'
    bars = rows[-120:]
    fig, ax = plt.subplots(figsize=(12, 6), dpi=120)
    try:
        fig.patch.set_facecolor('#101722')
        ax.set_facecolor('#101722')
        for i, (_, op, high, low, close) in enumerate(bars):
            color = '#4ecb93' if close >= op else '#f07878'
            ax.vlines(i, low, high, color=color, linewidth=.8)
            height = abs(close-op)
            if height == 0:
                ax.hlines(close, i-.3, i+.3, color=color, linewidth=1.2)
            else:
                ax.add_patch(Rectangle((i-.3, min(op, close)), .6, height, color=color))
        # Warm up indicators on all available candles before selecting the visible window.
        closes = [r[4] for r in rows]
        for period, color in ((20, '#ffd166'), (50, '#79b8ff'), (200, '#db9fff')):
            ax.plot(range(len(bars)), ema(closes, period)[-len(bars):], color=color,
                    linewidth=1, label=f'EMA {period}')
        ax.autoscale_view()
        ax.grid(alpha=.15)
        ax.tick_params(colors='white', labelsize=8)
        points = list(range(0, len(bars), max(1, len(bars)//6)))
        ax.set_xticks(points, [bars[i][0].strftime('%H:%M:%S') for i in points], rotation=20)
        ax.set_title(f'{asset} | velas 10 s | UTC | {kind}', color='white')
        ax.legend(loc='upper left', fontsize=8)
        fig.tight_layout()
        tmp = path.with_suffix('.tmp.png')
        fig.savefig(tmp, facecolor=fig.get_facecolor())
        os.replace(tmp, path)
    finally:
        plt.close(fig)
    with sqlite3.connect(db_path) as db:
        db.execute('CREATE TABLE IF NOT EXISTS research_chart_snapshots ('
                   'asset TEXT NOT NULL, candle_time TEXT NOT NULL, image_path TEXT NOT NULL, '
                   'kind TEXT NOT NULL, signal_json TEXT, PRIMARY KEY(asset,candle_time))')
        db.execute('INSERT OR REPLACE INTO research_chart_snapshots VALUES (?,?,?,?,?)',
                   (asset, rows[-1][0].isoformat(), str(path), kind,
                    json.dumps(signal, sort_keys=True) if signal else None))
    return path
