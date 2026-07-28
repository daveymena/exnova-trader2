"""
ðŸš€ INTEGRACIÃ“N IA CON TRADING
Conecta predicciones de IA con decisiones de trading en tiempo real
Implementa recomendaciones automÃ¡ticamente
"""
import json
import time
from typing import Dict, List, Optional, Tuple
from pathlib import Path
from datetime import datetime

from .local_ai_predictor import get_local_ai_predictor
from .trade_persistence import get_trade_persistence


class AITradingIntegration:
    """
    Integra IA con sistema de trading
    - Carga predicciones del predictor local
    - Implementa recomendaciones
    - Modifica parÃ¡metros de trading
    - Registra decisiones
    """

    def __init__(self):
        self.name = "AI Trading Integration v1.0"
        self.version = "1.0"
        
        # Componentes
        self.predictor = get_local_ai_predictor()
        self.persistence = get_trade_persistence()
        
        # ConfiguraciÃ³n de trading
        self.config = {
            'paused_assets': [],
            'volume_multipliers': {},
            'min_confidence': 0.50,
            'pattern_requirements': {},
            'zone_requirements': {}
        }
        
        # Historial de decisiones
        self.decisions = []
        self.applied_recommendations = []
        
        print(f"[OK] {self.name} inicializado")
        self._load_recommendations()

    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    # CARGA DE RECOMENDACIONES
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

    def _load_recommendations(self) -> None:
        """Carga recomendaciones del archivo de configuraciÃ³n"""
        
        try:
            rec_file = Path("bot/brain/recommendations_config.json")
            if rec_file.exists():
                with open(rec_file, 'r') as f:
                    rec_data = json.load(f)
                
                # Aplicar recomendaciones
                self.config['paused_assets'] = rec_data.get('paused_assets', [])
                self.config['volume_multipliers'] = rec_data.get('priority_assets', {})
                
                print(f"[OK] Recomendaciones cargadas")
                print(f"    Activos pausados: {self.config['paused_assets']}")
                print(f"    Activos prioritarios: {list(self.config['volume_multipliers'].keys())}")
            else:
                print(f"[!] Archivo de recomendaciones no encontrado")
        except Exception as e:
            print(f"[ERROR] Error cargando recomendaciones: {e}")

    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    # DECISIONES DE TRADING
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

    def should_trade_asset(self, asset: str) -> Tuple[bool, str]:
        """
        Determina si se debe tradear un activo
        Retorna (should_trade, reason)
        """
        
        # Verificar si estÃ¡ pausado
        if asset in self.config['paused_assets']:
            return False, f"Activo {asset} estÃ¡ pausado por IA"
        
        # Verificar estadÃ­sticas
        asset_stats = self.predictor.get_asset_stats(asset)
        if asset_stats:
            wr = asset_stats.get('win_rate', 0.5)
            if wr < 0.30:
                return False, f"Activo {asset} tiene WR muy baja ({wr:.1%})"
        
        return True, "OK"

    def get_trade_direction(self, market_context: Dict) -> Dict:
        """
        Obtiene direcciÃ³n recomendada para un trade
        """
        
        # Obtener predicciÃ³n de IA
        prediction = self.predictor.predict_next_move(market_context)
        
        decision = {
            'timestamp': time.time(),
            'asset': market_context.get('asset'),
            'prediction': prediction,
            'should_trade': prediction['confidence'] > self.config['min_confidence'],
            'direction': prediction['direction'],
            'confidence': prediction['confidence'],
            'action': prediction['action'],
            'reasoning': prediction['reasoning']
        }
        
        self.decisions.append(decision)
        return decision

    def get_volume_multiplier(self, asset: str) -> float:
        """
        Obtiene multiplicador de volumen para un activo
        """
        
        # Verificar si estÃ¡ en activos prioritarios
        if asset in self.config['volume_multipliers']:
            multiplier = self.config['volume_multipliers'][asset].get('volume_multiplier', 1.0)
            return multiplier
        
        # Verificar estadÃ­sticas locales
        asset_stats = self.predictor.get_asset_stats(asset)
        if asset_stats:
            wr = asset_stats.get('win_rate', 0.5)
            
            if wr > 0.60:
                return 1.5  # Aumentar 50%
            elif wr > 0.55:
                return 1.3  # Aumentar 30%
            elif wr < 0.40:
                return 0.5  # Reducir 50%
        
        return 1.0  # Sin cambios

    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    # ANÃLISIS Y RECOMENDACIONES
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

    def analyze_and_recommend(self) -> Dict:
        """
        Analiza datos histÃ³ricos y genera recomendaciones
        """
        
        print(f"\n[*] Analizando datos y generando recomendaciones...")
        
        analysis = self.predictor.analyze_trades()
        
        recommendations = {
            'timestamp': time.time(),
            'analysis': analysis,
            'actions': [],
            'expected_improvement': {}
        }
        
        # Generar acciones
        if analysis.get('best_assets'):
            for asset_info in analysis['best_assets']:
                asset = asset_info['asset']
                wr = asset_info['wr']
                
                if wr > 0.60:
                    recommendations['actions'].append({
                        'type': 'INCREASE_VOLUME',
                        'asset': asset,
                        'multiplier': 1.5,
                        'reason': f"WR {wr:.1%} - activo confiable"
                    })
        
        if analysis.get('worst_assets'):
            for asset_info in analysis['worst_assets']:
                asset = asset_info['asset']
                wr = asset_info['wr']
                
                if wr < 0.30:
                    recommendations['actions'].append({
                        'type': 'PAUSE_ASSET',
                        'asset': asset,
                        'reason': f"WR {wr:.1%} - muy bajo"
                    })
        
        # Proyectar mejora
        current_wr = analysis.get('win_rate', 0.5)
        recommendations['expected_improvement'] = {
            'current_wr': current_wr,
            'target_wr': min(0.65, current_wr + 0.10),
            'improvement_pct': ((min(0.65, current_wr + 0.10) - current_wr) / current_wr * 100) if current_wr > 0 else 0
        }
        
        self.applied_recommendations.append(recommendations)
        return recommendations

    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    # VALIDACIÃ“N DE TRADES
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

    def validate_trade(self, trade_params: Dict) -> Tuple[bool, str]:
        """
        Valida si un trade cumple con criterios de IA
        """
        
        asset = trade_params.get('asset')
        direction = trade_params.get('direction')
        confidence = trade_params.get('confidence', 0)
        pattern = trade_params.get('pattern', 'none')
        
        # ValidaciÃ³n 1: Activo no pausado
        should_trade, reason = self.should_trade_asset(asset)
        if not should_trade:
            return False, reason
        
        # ValidaciÃ³n 2: Confianza mÃ­nima
        if confidence < self.config['min_confidence']:
            return False, f"Confianza {confidence:.1%} < mÃ­nima {self.config['min_confidence']:.1%}"
        
        # ValidaciÃ³n 3: PatrÃ³n vÃ¡lido
        if pattern != 'none':
            pattern_stats = self.predictor.get_pattern_stats(pattern)
            if pattern_stats:
                wr = pattern_stats.get('win_rate', 0.5)
                if wr < 0.40:
                    return False, f"PatrÃ³n {pattern} tiene WR baja ({wr:.1%})"
        
        return True, "OK"

    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    # MONITOREO Y REPORTES
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

    def get_status(self) -> Dict:
        """Estado actual de la integraciÃ³n"""
        return {
            'name': self.name,
            'version': self.version,
            'paused_assets': self.config['paused_assets'],
            'volume_multipliers': self.config['volume_multipliers'],
            'decisions_made': len(self.decisions),
            'recommendations_applied': len(self.applied_recommendations),
            'predictor_status': self.predictor.get_summary(),
            'status': 'ACTIVE'
        }

    def generate_report(self) -> str:
        """Genera reporte de integraciÃ³n"""
        
        analysis = self.predictor.analyze_trades()
        
        report = f"""
â•”â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•—
â•‘                    ðŸ¤– REPORTE DE INTEGRACIÃ“N IA-TRADING                       â•‘
â•šâ•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

ðŸ“Š ANÃLISIS DE DATOS HISTÃ“RICOS:
  â€¢ Total de trades: {analysis['total_trades']}
  â€¢ Ganancias: {analysis['wins']} ({analysis['win_rate']:.1%})
  â€¢ PÃ©rdidas: {analysis['losses']} ({1-analysis['win_rate']:.1%})
  â€¢ PnL Total: {analysis['pnl_total']:+.2f}
  â€¢ PnL Promedio: {analysis['pnl_avg']:+.2f}

ðŸ† MEJORES ACTIVOS:
"""
        
        for asset_info in analysis.get('best_assets', []):
            report += f"  â€¢ {asset_info['asset']}: WR {asset_info['wr']:.1%}, PnL {asset_info['pnl']:+.2f}\n"
        
        report += f"""
âš ï¸  PEORES ACTIVOS:
"""
        
        for asset_info in analysis.get('worst_assets', []):
            report += f"  â€¢ {asset_info['asset']}: WR {asset_info['wr']:.1%}, PnL {asset_info['pnl']:+.2f}\n"
        
        report += f"""
ðŸŽ¯ RECOMENDACIONES:
"""
        
        for rec in analysis.get('recommendations', []):
            report += f"  â€¢ {rec}\n"
        
        report += f"""
âš™ï¸  CONFIGURACIÃ“N ACTUAL:
  â€¢ Activos pausados: {', '.join(self.config['paused_assets']) if self.config['paused_assets'] else 'Ninguno'}
  â€¢ Activos prioritarios: {', '.join(self.config['volume_multipliers'].keys()) if self.config['volume_multipliers'] else 'Ninguno'}
  â€¢ Confianza mÃ­nima: {self.config['min_confidence']:.1%}

ðŸ“ˆ DECISIONES TOMADAS:
  â€¢ Total: {len(self.decisions)}
  â€¢ Ãšltimas 5:
"""
        
        for decision in self.decisions[-5:]:
            report += f"    - {decision['asset']}: {decision['direction']} (conf {decision['confidence']:.0f}%)\n"
        
        report += f"""
{'='*80}
"""
        
        return report

    def get_summary(self) -> Dict:
        """Resumen ejecutivo"""
        analysis = self.predictor.analyze_trades()
        
        return {
            'name': self.name,
            'version': self.version,
            'trades_analyzed': analysis['total_trades'],
            'current_wr': analysis['win_rate'],
            'current_pnl': analysis['pnl_total'],
            'paused_assets': self.config['paused_assets'],
            'decisions_made': len(self.decisions),
            'status': 'ACTIVE'
        }


# Singleton
_integration: Optional[AITradingIntegration] = None


def get_ai_trading_integration() -> AITradingIntegration:
    global _integration
    if _integration is None:
        _integration = AITradingIntegration()
    return _integration


if __name__ == "__main__":
    # Prueba
    integration = get_ai_trading_integration()
    
    print(f"\n{integration.generate_report()}")
    
    # Ejemplo de predicciÃ³n
    market_context = {
        'asset': 'EURJPY-OTC',
        'price': 150.5,
        'rsi': 25,
        'trend': 'DOWN',
        'pattern': 'pin_bar_bullish',
        'nearby_zone': 150.0
    }
    
    decision = integration.get_trade_direction(market_context)
    print(f"\n[*] PredicciÃ³n para {market_context['asset']}:")
    print(f"    DirecciÃ³n: {decision['direction']}")
    print(f"    Confianza: {decision['confidence']:.0f}%")
    print(f"    AcciÃ³n: {decision['action']}")
    print(f"    Razones: {', '.join(decision['reasoning'])}")

