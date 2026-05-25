"""
🧠 PREDICTOR LOCAL DE IA
Sistema de predicción basado en análisis local de datos históricos
NO requiere API externa - funciona 100% offline
"""
import json
import time
from typing import Dict, List, Optional, Tuple
from pathlib import Path
from datetime import datetime
import statistics


class LocalAIPredictor:
    """
    Predictor de IA basado en análisis local
    Aprende de trades históricos y genera predicciones
    """

    def __init__(self, trade_history_file: str = "bot/brain/trade_history.json"):
        self.name = "Local AI Predictor v1.0"
        self.version = "1.0"
        self.trade_history_file = Path(trade_history_file)
        
        # Datos históricos
        self.trades = []
        self.asset_stats = {}
        self.pattern_stats = {}
        self.zone_stats = {}
        
        # Caché de análisis
        self.analysis_cache = {}
        self.predictions_made = []
        
        print(f"[OK] {self.name} inicializado")
        self._load_trade_history()
        self._analyze_historical_data()

    # ═══════════════════════════════════════════════════════════════════════════════
    # CARGA Y ANÁLISIS DE DATOS HISTÓRICOS
    # ═══════════════════════════════════════════════════════════════════════════════

    def _load_trade_history(self) -> None:
        """Carga trades históricos"""
        try:
            if self.trade_history_file.exists():
                with open(self.trade_history_file, 'r') as f:
                    data = json.load(f)
                    self.trades = data if isinstance(data, list) else data.get('trades', [])
                print(f"[OK] {len(self.trades)} trades cargados")
            else:
                print(f"[!] Archivo de trades no encontrado")
                self.trades = []
        except Exception as e:
            print(f"[ERROR] Error cargando trades: {e}")
            self.trades = []

    def _analyze_historical_data(self) -> None:
        """Analiza datos históricos para extraer patrones"""
        
        if not self.trades:
            print(f"[!] No hay trades para analizar")
            return
        
        print(f"\n[*] Analizando {len(self.trades)} trades históricos...")
        
        # Análisis por activo
        for trade in self.trades:
            asset = trade.get('asset', 'UNKNOWN')
            result = trade.get('result', 'UNKNOWN')
            pattern = trade.get('pattern', 'none')
            rsi = trade.get('rsi_at_touch', 50)
            pnl = trade.get('pnl', 0)
            zone = trade.get('zone', 'unknown')
            
            # Estadísticas por activo
            if asset not in self.asset_stats:
                self.asset_stats[asset] = {
                    'total': 0, 'wins': 0, 'losses': 0,
                    'pnl_total': 0, 'pnl_avg': 0,
                    'rsi_avg': 0, 'rsi_values': []
                }
            
            stats = self.asset_stats[asset]
            stats['total'] += 1
            stats['pnl_total'] += pnl
            stats['rsi_values'].append(rsi)
            
            if result == 'HOLD':
                stats['wins'] += 1
            elif result == 'BREAK':
                stats['losses'] += 1
            
            # Estadísticas por patrón
            if pattern not in self.pattern_stats:
                self.pattern_stats[pattern] = {
                    'total': 0, 'wins': 0, 'losses': 0,
                    'pnl_total': 0, 'confidence': 0
                }
            
            pstats = self.pattern_stats[pattern]
            pstats['total'] += 1
            pstats['pnl_total'] += pnl
            if result == 'HOLD':
                pstats['wins'] += 1
            else:
                pstats['losses'] += 1
            
            # Estadísticas por zona
            if zone not in self.zone_stats:
                self.zone_stats[zone] = {
                    'total': 0, 'wins': 0, 'losses': 0,
                    'hold_rate': 0
                }
            
            zstats = self.zone_stats[zone]
            zstats['total'] += 1
            if result == 'HOLD':
                zstats['wins'] += 1
            else:
                zstats['losses'] += 1
        
        # Calcular promedios
        for asset, stats in self.asset_stats.items():
            if stats['total'] > 0:
                stats['pnl_avg'] = stats['pnl_total'] / stats['total']
                stats['rsi_avg'] = statistics.mean(stats['rsi_values']) if stats['rsi_values'] else 50
                stats['win_rate'] = stats['wins'] / stats['total']
        
        for pattern, stats in self.pattern_stats.items():
            if stats['total'] > 0:
                stats['win_rate'] = stats['wins'] / stats['total']
                stats['confidence'] = min(100, (stats['total'] / 5) * 100)  # Confianza basada en muestras
        
        for zone, stats in self.zone_stats.items():
            if stats['total'] > 0:
                stats['hold_rate'] = stats['wins'] / stats['total']
        
        print(f"[OK] Análisis completado")
        print(f"    Activos: {len(self.asset_stats)}")
        print(f"    Patrones: {len(self.pattern_stats)}")
        print(f"    Zonas: {len(self.zone_stats)}")

    # ═══════════════════════════════════════════════════════════════════════════════
    # PREDICCIÓN DE MOVIMIENTOS
    # ═══════════════════════════════════════════════════════════════════════════════

    def predict_next_move(self, market_context: Dict) -> Dict:
        """
        Predice el próximo movimiento basado en contexto actual
        """
        asset = market_context.get('asset', 'UNKNOWN')
        price = market_context.get('price', 0)
        rsi = market_context.get('rsi', 50)
        trend = market_context.get('trend', 'NEUTRAL')
        pattern = market_context.get('pattern', 'none')
        nearby_zone = market_context.get('nearby_zone', None)
        
        prediction = {
            'timestamp': time.time(),
            'asset': asset,
            'direction': 'NEUTRAL',
            'confidence': 0,
            'reasoning': [],
            'factors': {}
        }
        
        # Factor 1: Historial del activo
        if asset in self.asset_stats:
            asset_stats = self.asset_stats[asset]
            wr = asset_stats.get('win_rate', 0.5)
            
            if wr > 0.55:
                prediction['direction'] = 'CALL'
                prediction['confidence'] += 20
                prediction['reasoning'].append(f"Activo {asset} tiene WR {wr:.1%}")
            elif wr < 0.45:
                prediction['direction'] = 'PUT'
                prediction['confidence'] += 20
                prediction['reasoning'].append(f"Activo {asset} tiene WR baja {wr:.1%}")
            
            prediction['factors']['asset_wr'] = wr
        
        # Factor 2: Patrón
        if pattern in self.pattern_stats:
            pattern_stats = self.pattern_stats[pattern]
            wr = pattern_stats.get('win_rate', 0.5)
            confidence = pattern_stats.get('confidence', 0)
            
            if wr > 0.55 and confidence > 50:
                prediction['confidence'] += 15
                prediction['reasoning'].append(f"Patrón {pattern} tiene WR {wr:.1%}")
            
            prediction['factors']['pattern_wr'] = wr
            prediction['factors']['pattern_confidence'] = confidence
        
        # Factor 3: RSI
        if rsi < 30:
            prediction['direction'] = 'CALL'
            prediction['confidence'] += 25
            prediction['reasoning'].append(f"RSI {rsi} indica sobreventa")
        elif rsi > 70:
            prediction['direction'] = 'PUT'
            prediction['confidence'] += 25
            prediction['reasoning'].append(f"RSI {rsi} indica sobrecompra")
        
        prediction['factors']['rsi'] = rsi
        
        # Factor 4: Zona cercana
        if nearby_zone and nearby_zone in self.zone_stats:
            zone_stats = self.zone_stats[nearby_zone]
            hold_rate = zone_stats.get('hold_rate', 0.5)
            
            if hold_rate > 0.7:
                prediction['confidence'] += 15
                prediction['reasoning'].append(f"Zona {nearby_zone} tiene hold rate {hold_rate:.1%}")
            elif hold_rate < 0.3:
                prediction['confidence'] -= 10
                prediction['reasoning'].append(f"Zona {nearby_zone} es débil (hold rate {hold_rate:.1%})")
            
            prediction['factors']['zone_hold_rate'] = hold_rate
        
        # Factor 5: Tendencia (invertida según análisis)
        # Los datos muestran que 86.4% de ganancias son CONTRA tendencia
        if trend == 'UP':
            prediction['direction'] = 'PUT'  # Invertido
            prediction['confidence'] += 10
            prediction['reasoning'].append("Tendencia UP → Predicción PUT (reversión)")
        elif trend == 'DOWN':
            prediction['direction'] = 'CALL'  # Invertido
            prediction['confidence'] += 10
            prediction['reasoning'].append("Tendencia DOWN → Predicción CALL (reversión)")
        
        prediction['factors']['trend'] = trend
        
        # Limitar confianza a 100
        prediction['confidence'] = min(100, max(0, prediction['confidence']))
        
        # Acción recomendada
        if prediction['confidence'] > 70:
            prediction['action'] = 'STRONG_ENTER'
        elif prediction['confidence'] > 60:
            prediction['action'] = 'ENTER'
        elif prediction['confidence'] > 50:
            prediction['action'] = 'WEAK_ENTER'
        else:
            prediction['action'] = 'WAIT'
        
        self.predictions_made.append(prediction)
        return prediction

    # ═══════════════════════════════════════════════════════════════════════════════
    # ANÁLISIS DE TRADES
    # ═══════════════════════════════════════════════════════════════════════════════

    def analyze_trades(self) -> Dict:
        """Análisis completo de trades históricos"""
        
        if not self.trades:
            return {'status': 'no_data'}
        
        wins = [t for t in self.trades if t.get('result') == 'HOLD']
        losses = [t for t in self.trades if t.get('result') == 'BREAK']
        
        analysis = {
            'total_trades': len(self.trades),
            'wins': len(wins),
            'losses': len(losses),
            'win_rate': len(wins) / len(self.trades) if self.trades else 0,
            'pnl_total': sum(t.get('pnl', 0) for t in self.trades),
            'pnl_avg': sum(t.get('pnl', 0) for t in self.trades) / len(self.trades) if self.trades else 0,
            
            'best_assets': self._get_best_assets(3),
            'worst_assets': self._get_worst_assets(3),
            'best_patterns': self._get_best_patterns(3),
            'worst_patterns': self._get_worst_patterns(3),
            
            'recommendations': self._generate_recommendations()
        }
        
        return analysis

    def _get_best_assets(self, n: int = 3) -> List[Dict]:
        """Mejores activos por WR"""
        sorted_assets = sorted(
            self.asset_stats.items(),
            key=lambda x: x[1].get('win_rate', 0),
            reverse=True
        )
        return [
            {
                'asset': asset,
                'wr': stats['win_rate'],
                'pnl': stats['pnl_total'],
                'trades': stats['total']
            }
            for asset, stats in sorted_assets[:n]
        ]

    def _get_worst_assets(self, n: int = 3) -> List[Dict]:
        """Peores activos por WR"""
        sorted_assets = sorted(
            self.asset_stats.items(),
            key=lambda x: x[1].get('win_rate', 0)
        )
        return [
            {
                'asset': asset,
                'wr': stats['win_rate'],
                'pnl': stats['pnl_total'],
                'trades': stats['total']
            }
            for asset, stats in sorted_assets[:n]
        ]

    def _get_best_patterns(self, n: int = 3) -> List[Dict]:
        """Mejores patrones por WR"""
        sorted_patterns = sorted(
            self.pattern_stats.items(),
            key=lambda x: x[1].get('win_rate', 0),
            reverse=True
        )
        return [
            {
                'pattern': pattern,
                'wr': stats['win_rate'],
                'confidence': stats['confidence'],
                'trades': stats['total']
            }
            for pattern, stats in sorted_patterns[:n]
        ]

    def _get_worst_patterns(self, n: int = 3) -> List[Dict]:
        """Peores patrones por WR"""
        sorted_patterns = sorted(
            self.pattern_stats.items(),
            key=lambda x: x[1].get('win_rate', 0)
        )
        return [
            {
                'pattern': pattern,
                'wr': stats['win_rate'],
                'confidence': stats['confidence'],
                'trades': stats['total']
            }
            for pattern, stats in sorted_patterns[:n]
        ]

    def _generate_recommendations(self) -> List[str]:
        """Genera recomendaciones basadas en análisis"""
        recommendations = []
        
        # Recomendar pausar activos malos
        for asset, stats in self.asset_stats.items():
            if stats['total'] >= 5 and stats['win_rate'] < 0.30:
                recommendations.append(f"PAUSAR {asset} (WR {stats['win_rate']:.1%})")
        
        # Recomendar aumentar volumen en activos buenos
        for asset, stats in self.asset_stats.items():
            if stats['total'] >= 5 and stats['win_rate'] > 0.60:
                recommendations.append(f"AUMENTAR volumen en {asset} (WR {stats['win_rate']:.1%})")
        
        # Recomendar patrones
        for pattern, stats in self.pattern_stats.items():
            if stats['total'] >= 3 and stats['win_rate'] > 0.70:
                recommendations.append(f"PRIORIZAR patrón {pattern} (WR {stats['win_rate']:.1%})")
        
        return recommendations

    # ═══════════════════════════════════════════════════════════════════════════════
    # UTILIDADES
    # ═══════════════════════════════════════════════════════════════════════════════

    def get_asset_stats(self, asset: str) -> Optional[Dict]:
        """Obtiene estadísticas de un activo"""
        return self.asset_stats.get(asset)

    def get_pattern_stats(self, pattern: str) -> Optional[Dict]:
        """Obtiene estadísticas de un patrón"""
        return self.pattern_stats.get(pattern)

    def get_summary(self) -> Dict:
        """Resumen del predictor"""
        return {
            'name': self.name,
            'version': self.version,
            'trades_analyzed': len(self.trades),
            'assets_tracked': len(self.asset_stats),
            'patterns_tracked': len(self.pattern_stats),
            'zones_tracked': len(self.zone_stats),
            'predictions_made': len(self.predictions_made),
            'status': 'ACTIVE'
        }


# Singleton
_predictor: Optional[LocalAIPredictor] = None


def get_local_ai_predictor() -> LocalAIPredictor:
    global _predictor
    if _predictor is None:
        _predictor = LocalAIPredictor()
    return _predictor
