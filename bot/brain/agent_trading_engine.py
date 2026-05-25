"""
🚀 MOTOR DE TRADING CON AGENTE INTELIGENTE
Integra el agente inteligente con el sistema de trading
Reemplaza la lógica de decisión actual
"""
import json
import os
import time
from typing import Dict, List, Optional, Tuple
from pathlib import Path

from .intelligent_trading_agent import get_intelligent_trading_agent
from .trade_persistence import get_trade_persistence


class AgentTradingEngine:
    """
    Motor de trading que usa el agente inteligente
    - Contexto completo
    - Detección automática de incoherencias
    - IA estratégica
    - Mejora continua
    """

    def __init__(self, github_token: str):
        self.name = "Agent Trading Engine v1.0"
        self.version = "1.0"
        
        # Componentes
        self.agent = get_intelligent_trading_agent(github_token)
        self.persistence = get_trade_persistence()
        
        # Configuración
        self.config = {
            'min_confidence': 0.20,
            'use_ai': True,
            'auto_correct': True,
            'learn_from_trades': True
        }
        
        # Historial
        self.trades_executed = []
        self.decisions_log = []
        
        print(f"[OK] {self.name} inicializado")

    # ═══════════════════════════════════════════════════════════════════════════════
    # DECISIÓN DE TRADING
    # ═══════════════════════════════════════════════════════════════════════════════

    def should_trade(self, market_context: Dict) -> Tuple[bool, Dict]:
        """
        Determina si se debe tradear
        Retorna (should_trade, analysis)
        """
        
        # Analizar con agente
        analysis = self.agent.analyze_trade_opportunity(market_context)
        
        # Decisión
        should_trade = analysis['decision'] in ['ENTER', 'STRONG_ENTER']
        
        return should_trade, analysis

    def get_trade_direction(self, market_context: Dict) -> Tuple[str, float, Dict]:
        """
        Obtiene dirección de trade
        Retorna (direction, confidence, analysis)
        """
        
        # Analizar con agente
        analysis = self.agent.analyze_trade_opportunity(market_context)
        
        direction = analysis['direction']
        confidence = analysis['confidence'] / 100.0
        
        return direction, confidence, analysis

    def get_volume_multiplier(self, asset: str) -> float:
        """
        Obtiene multiplicador de volumen para un activo
        """
        
        # Usar reglas aprendidas del agente
        if asset in self.agent.learned_rules['asset_logic']:
            asset_rule = self.agent.learned_rules['asset_logic'][asset]
            return asset_rule.get('volume_mult', 1.0)
        
        return 1.0

    # ═══════════════════════════════════════════════════════════════════════════════
    # EJECUCIÓN DE TRADE
    # ═══════════════════════════════════════════════════════════════════════════════

    def execute_trade(self, trade_params: Dict) -> Dict:
        """
        Ejecuta un trade con validación del agente
        """
        
        trade_result = {
            'timestamp': time.time(),
            'asset': trade_params.get('asset'),
            'direction': trade_params.get('direction'),
            'amount': trade_params.get('amount'),
            'executed': False,
            'reason': None,
            'agent_analysis': None,
            'corrections': []
        }
        
        # Obtener análisis del agente
        market_context = {
            'asset': trade_params.get('asset'),
            'price': trade_params.get('price'),
            'rsi': trade_params.get('rsi'),
            'trend': trade_params.get('trend'),
            'pattern': trade_params.get('pattern'),
            'zone_type': trade_params.get('zone_type'),
            'zone': trade_params.get('zone'),
            'direction': trade_params.get('direction')
        }
        
        analysis = self.agent.analyze_trade_opportunity(market_context)
        trade_result['agent_analysis'] = analysis
        
        # Verificar incoherencias
        if analysis['incoherences_detected']:
            if self.config['auto_correct']:
                # Aplicar correcciones
                for incoherence in analysis['incoherences_detected']:
                    correction = self.agent.auto_correct_incoherence(incoherence)
                    trade_result['corrections'].append(correction)
                
                # Usar dirección corregida
                trade_result['direction'] = analysis['direction']
        
        # Verificar confianza
        if analysis['confidence'] < self.config['min_confidence'] * 100:
            trade_result['executed'] = False
            trade_result['reason'] = f"Confianza baja ({analysis['confidence']:.0f}%)"
            return trade_result
        
        # Verificar decisión
        if analysis['decision'] not in ['ENTER', 'STRONG_ENTER']:
            trade_result['executed'] = False
            trade_result['reason'] = f"Decisión: {analysis['decision']}"
            return trade_result
        
        # Trade aprobado
        trade_result['executed'] = True
        trade_result['reason'] = "Aprobado por agente"
        
        self.trades_executed.append(trade_result)
        
        return trade_result

    # ═══════════════════════════════════════════════════════════════════════════════
    # APRENDIZAJE
    # ═══════════════════════════════════════════════════════════════════════════════

    def record_trade_result(self, trade: Dict) -> None:
        """
        Registra resultado de trade y aprende
        """
        
        if self.config['learn_from_trades']:
            self.agent.learn_from_trade_result(trade)
        
        # Guardar en persistencia
        self.persistence.add_trade(trade)

    # ═══════════════════════════════════════════════════════════════════════════════
    # MONITOREO
    # ═══════════════════════════════════════════════════════════════════════════════

    def get_status(self) -> Dict:
        """Estado del motor"""
        
        agent_status = self.agent.get_status()
        
        return {
            'name': self.name,
            'version': self.version,
            'agent': agent_status,
            'trades_executed': len(self.trades_executed),
            'config': self.config,
            'status': 'ACTIVE'
        }

    def generate_report(self) -> str:
        """Genera reporte del motor"""
        
        status = self.get_status()
        agent_status = status['agent']
        
        report = f"""
╔════════════════════════════════════════════════════════════════════════════════╗
║                    🚀 REPORTE DEL MOTOR DE TRADING                            ║
╚════════════════════════════════════════════════════════════════════════════════╝

🤖 AGENTE INTELIGENTE:
  • Nombre: {agent_status['name']}
  • Versión: {agent_status['version']}
  • Autenticado: {'Sí' if agent_status['authenticated'] else 'No'}

📊 CONTEXTO:
  • Trades analizados: {agent_status['context']['trades_analyzed']}
  • Win Rate: {agent_status['context']['win_rate']:.1%}
  • PnL Total: {agent_status['context']['pnl_total']:+.2f}

🎯 DECISIONES:
  • Total: {agent_status['decisions_made']}
  • Incoherencias corregidas: {agent_status['incoherences_fixed']}

🧠 EFICIENCIA DE IA:
  • Llamadas realizadas: {agent_status['ai_calls_made']}
  • Llamadas ahorradas: {agent_status['ai_calls_saved']}
  • Eficiencia: {agent_status['efficiency']}

⚙️  CONFIGURACIÓN:
  • Confianza mínima: {self.config['min_confidence']:.0%}
  • Usar IA: {'Sí' if self.config['use_ai'] else 'No'}
  • Auto-corrección: {'Sí' if self.config['auto_correct'] else 'No'}
  • Aprendizaje: {'Sí' if self.config['learn_from_trades'] else 'No'}

📈 TRADES EJECUTADOS:
  • Total: {len(self.trades_executed)}

{'='*80}
"""
        
        return report

    def get_summary(self) -> Dict:
        """Resumen ejecutivo"""
        
        agent_summary = self.agent.get_summary()
        
        return {
            'name': self.name,
            'version': self.version,
            'agent': agent_summary,
            'trades_executed': len(self.trades_executed),
            'status': 'ACTIVE'
        }


# Singleton
_engine: Optional[AgentTradingEngine] = None


def get_agent_trading_engine(github_token: str) -> AgentTradingEngine:
    global _engine
    if _engine is None:
        _engine = AgentTradingEngine(github_token)
    return _engine


if __name__ == "__main__":
    # Token de GitHub (usar variable de entorno)
    token = os.environ.get("GITHUB_TOKEN", "")
    
    engine = get_agent_trading_engine(token)
    
    # Mostrar estado
    print(engine.generate_report())
    
    # Ejemplo de decisión
    market_context = {
        'asset': 'EURJPY-OTC',
        'price': 150.5,
        'rsi': 25,
        'trend': 'DOWN',
        'pattern': 'pin_bar_bullish',
        'zone_type': 'support',
        'zone': 150.0
    }
    
    print("\n[*] Verificando si se debe tradear...")
    should_trade, analysis = engine.should_trade(market_context)
    
    print(f"¿Tradear?: {should_trade}")
    print(f"Decisión: {analysis['decision']}")
    print(f"Dirección: {analysis['direction']}")
    print(f"Confianza: {analysis['confidence']:.0f}%")
    
    # Ejemplo de ejecución
    if should_trade:
        print("\n[*] Ejecutando trade...")
        trade_params = {
            'asset': 'EURJPY-OTC',
            'direction': analysis['direction'],
            'price': 150.5,
            'rsi': 25,
            'trend': 'DOWN',
            'pattern': 'pin_bar_bullish',
            'zone_type': 'support',
            'zone': 150.0,
            'amount': 100
        }
        
        result = engine.execute_trade(trade_params)
        
        print(f"Ejecutado: {result['executed']}")
        print(f"Razón: {result['reason']}")
        print(f"Correcciones: {len(result['corrections'])}")
