"""
Intelligent Trader - Sistema de Trading Inteligente
Combina análisis técnico, Smart Money concepts y aprendizaje profesional
para tomar decisiones como un trader institucional
"""
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
import logging

from core.smart_money_analyzer import SmartMoneyAnalyzer
from core.professional_learning_system import ProfessionalLearningSystem, MarketPhase, TradingConcept
from core.market_structure_analyzer import MarketStructureAnalyzer

logger = logging.getLogger(__name__)

class IntelligentTrader:
    """
    Sistema de trading inteligente que:
    1. Analiza estructura de mercado como un trader profesional
    2. Identifica conceptos Smart Money
    3. Aprende de experiencias pasadas
    4. Toma decisiones basadas en confluencias múltiples
    5. Se adapta continuamente al mercado
    """
    
    def __init__(self, llm_client=None):
        self.smart_money_analyzer = SmartMoneyAnalyzer()
        self.professional_learning = ProfessionalLearningSystem()
        self.market_structure_analyzer = MarketStructureAnalyzer()
        self.llm_client = llm_client
        
        # Configuración de decisiones
        self.min_confluence_score = 70  # Mínimo score de confluencia
        self.max_risk_per_trade = 0.02  # Máximo 2% de riesgo por operación
        self.required_edge = 0.65  # Ventaja mínima requerida (65%)
        
        # Tracking de performance
        self.session_stats = {
            'total_analyses': 0,
            'signals_generated': 0,
            'trades_executed': 0,
            'confluence_scores': [],
            'concepts_used': {}
        }
    
    def analyze_trading_opportunity(self, candles: pd.DataFrame, asset: str, 
                                 current_balance: float) -> Dict:
        """
        Análisis completo de oportunidad de trading usando todos los sistemas
        
        Returns:
            Dict con análisis completo y recomendación final
        """
        self.session_stats['total_analyses'] += 1
        
        try:
            # 1. Análisis de estructura básica
            basic_structure = self.market_structure_analyzer.analyze_full_context(candles)
            
            # 2. Análisis Smart Money completo
            smart_money_analysis = self.smart_money_analyzer.analyze_smart_money_structure(candles)
            
            # 3. Determinar fase de mercado
            market_phase = self._determine_current_market_phase(basic_structure, smart_money_analysis)
            
            # 4. Identificar concepto principal
            primary_concept = self._identify_primary_trading_concept(smart_money_analysis)
            
            # 5. Consultar aprendizaje profesional
            learning_recommendation = self._get_learning_recommendation(
                primary_concept, market_phase, candles
            )
            
            # 6. Calcular confluencias
            confluence_analysis = self._calculate_confluences(
                basic_structure, smart_money_analysis, learning_recommendation
            )
            
            # 7. Análisis de timing con LLM (si disponible)
            llm_timing_analysis = None
            if self.llm_client:
                llm_timing_analysis = self._get_llm_timing_analysis(
                    candles, confluence_analysis, asset
                )
            
            # 8. Generar decisión final
            final_decision = self._generate_final_decision(
                confluence_analysis, learning_recommendation, llm_timing_analysis,
                asset, current_balance
            )
            
            # 9. Actualizar estadísticas
            self._update_session_stats(final_decision, primary_concept)
            
            return {
                'timestamp': datetime.now().isoformat(),
                'asset': asset,
                'market_phase': market_phase.value,
                'primary_concept': primary_concept.value,
                'basic_structure': basic_structure,
                'smart_money_analysis': smart_money_analysis,
                'learning_recommendation': learning_recommendation,
                'confluence_analysis': confluence_analysis,
                'llm_timing_analysis': llm_timing_analysis,
                'final_decision': final_decision,
                'session_stats': self.session_stats.copy()
            }
            
        except Exception as e:
            logger.error(f"Error en análisis inteligente: {e}")
            return self._generate_error_response(str(e))
    
    def _determine_current_market_phase(self, basic_structure: Dict, 
                                      smart_money_analysis: Dict) -> MarketPhase:
        """Determina la fase actual del mercado"""
        
        # Usar análisis básico como base
        basic_phase = basic_structure.get('market_phase', 'ranging')
        
        # Refinar con análisis Smart Money
        directional_bias = smart_money_analysis.get('directional_bias', {})
        market_structure = smart_money_analysis.get('market_structure', {})
        
        # Lógica de determinación de fase
        if basic_phase == 'accumulation':
            # Verificar si realmente es acumulación o ranging
            if directional_bias.get('confidence', 0) < 60:
                return MarketPhase.RANGING
            return MarketPhase.ACCUMULATION
        
        elif basic_phase == 'markup':
            # Verificar fuerza del markup
            if market_structure.get('bos') and directional_bias.get('bias') == 'bullish':
                return MarketPhase.MARKUP
            return MarketPhase.RANGING
        
        elif basic_phase == 'distribution':
            if directional_bias.get('confidence', 0) < 60:
                return MarketPhase.RANGING
            return MarketPhase.DISTRIBUTION
        
        elif basic_phase == 'markdown':
            if market_structure.get('bos') and directional_bias.get('bias') == 'bearish':
                return MarketPhase.MARKDOWN
            return MarketPhase.RANGING
        
        else:
            return MarketPhase.RANGING
    
    def _identify_primary_trading_concept(self, smart_money_analysis: Dict) -> TradingConcept:
        """Identifica el concepto principal de trading"""
        
        # Priorizar por fuerza de señal
        if smart_money_analysis.get('order_blocks'):
            fresh_obs = [ob for ob in smart_money_analysis['order_blocks'] if not ob.get('mitigated', False)]
            if fresh_obs:
                return TradingConcept.ORDER_BLOCK
        
        if smart_money_analysis.get('fair_value_gaps'):
            unfilled_fvgs = [fvg for fvg in smart_money_analysis['fair_value_gaps'] if not fvg.get('filled', False)]
            if unfilled_fvgs:
                return TradingConcept.FAIR_VALUE_GAP
        
        market_structure = smart_money_analysis.get('market_structure', {})
        if market_structure.get('bos'):
            return TradingConcept.BREAK_OF_STRUCTURE
        
        if market_structure.get('choch'):
            return TradingConcept.CHANGE_OF_CHARACTER
        
        if smart_money_analysis.get('inducement_signals'):
            return TradingConcept.INDUCEMENT
        
        if smart_money_analysis.get('liquidity_zones'):
            return TradingConcept.LIQUIDITY_SWEEP
        
        # Default
        return TradingConcept.SMART_MONEY_REVERSAL
    
    def _get_learning_recommendation(self, concept: TradingConcept, 
                                   market_phase: MarketPhase, 
                                   candles: pd.DataFrame) -> Dict:
        """Obtiene recomendación del sistema de aprendizaje profesional"""
        
        # Extraer condiciones actuales
        current_conditions = self._extract_current_conditions(candles)
        
        # Consultar sistema de aprendizaje
        should_trade, confidence, reasons = self.professional_learning.should_trade_concept(
            concept, market_phase, current_conditions
        )
        
        # Obtener condiciones óptimas
        optimal_conditions = self.professional_learning.get_optimal_entry_conditions(
            concept, market_phase
        )
        
        return {
            'should_trade': should_trade,
            'confidence': confidence,
            'reasons': reasons,
            'optimal_conditions': optimal_conditions,
            'current_conditions': current_conditions,
            'concept': concept.value,
            'market_phase': market_phase.value
        }
    
    def _extract_current_conditions(self, candles: pd.DataFrame) -> List[str]:
        """Extrae condiciones actuales del mercado"""
        conditions = []
        
        if candles.empty or len(candles) < 10:
            return conditions
        
        last_candle = candles.iloc[-1]
        
        # Condiciones técnicas
        if 'rsi' in candles.columns:
            rsi = last_candle['rsi']
            if rsi < 30:
                conditions.append("RSI sobreventa")
            elif rsi > 70:
                conditions.append("RSI sobrecompra")
            else:
                conditions.append("RSI neutral")
        
        if 'macd' in candles.columns:
            macd = last_candle['macd']
            if macd > 0:
                conditions.append("MACD alcista")
            else:
                conditions.append("MACD bajista")
        
        # Condiciones de precio vs Bollinger Bands
        if all(col in candles.columns for col in ['bb_high', 'bb_low']):
            price = last_candle['close']
            bb_high = last_candle['bb_high']
            bb_low = last_candle['bb_low']
            
            if price <= bb_low:
                conditions.append("Precio en banda inferior")
            elif price >= bb_high:
                conditions.append("Precio en banda superior")
            else:
                conditions.append("Precio en rango normal")
        
        # Condiciones de volatilidad
        if len(candles) >= 20:
            recent_volatility = candles.tail(20)['close'].std()
            avg_volatility = candles['close'].std()
            
            if recent_volatility > avg_volatility * 1.5:
                conditions.append("Alta volatilidad")
            elif recent_volatility < avg_volatility * 0.5:
                conditions.append("Baja volatilidad")
            else:
                conditions.append("Volatilidad normal")
        
        return conditions
    
    def _calculate_confluences(self, basic_structure: Dict, smart_money_analysis: Dict, 
                             learning_recommendation: Dict) -> Dict:
        """Calcula confluencias entre diferentes análisis"""
        
        confluences = []
        total_score = 0
        max_possible_score = 0
        
        # 1. Confluencia de dirección (peso: 30)
        basic_direction = basic_structure.get('entry_signal', {}).get('direction')
        smart_direction = smart_money_analysis.get('entry_signal', {}).get('direction')
        
        max_possible_score += 30
        if basic_direction and smart_direction and basic_direction == smart_direction:
            total_score += 30
            confluences.append(f"Dirección confirmada: {basic_direction}")
        elif basic_direction or smart_direction:
            total_score += 15
            confluences.append("Dirección parcialmente confirmada")
        
        # 2. Confluencia de confianza (peso: 25)
        basic_confidence = basic_structure.get('entry_signal', {}).get('confidence', 0)
        smart_confidence = smart_money_analysis.get('confidence', 0)
        learning_confidence = learning_recommendation.get('confidence', 0)
        
        avg_confidence = (basic_confidence + smart_confidence + learning_confidence) / 3
        max_possible_score += 25
        
        if avg_confidence >= 0.8:
            total_score += 25
            confluences.append(f"Alta confianza promedio ({avg_confidence:.1%})")
        elif avg_confidence >= 0.6:
            total_score += 15
            confluences.append(f"Confianza moderada ({avg_confidence:.1%})")
        elif avg_confidence >= 0.4:
            total_score += 8
            confluences.append(f"Confianza baja ({avg_confidence:.1%})")
        
        # 3. Confluencia de aprendizaje (peso: 20)
        max_possible_score += 20
        if learning_recommendation.get('should_trade', False):
            total_score += 20
            confluences.append("Aprendizaje profesional confirma")
        else:
            confluences.append("Aprendizaje profesional advierte precaución")
        
        # 4. Confluencia de estructura Smart Money (peso: 15)
        max_possible_score += 15
        smart_entry = smart_money_analysis.get('entry_signal', {})
        if smart_entry.get('should_enter', False):
            total_score += 15
            confluences.append("Smart Money confirma entrada")
        elif len(smart_entry.get('entry_reasons', [])) > 0:
            total_score += 8
            confluences.append("Smart Money muestra interés parcial")
        
        # 5. Confluencia de timing (peso: 10)
        max_possible_score += 10
        basic_should_enter = basic_structure.get('entry_signal', {}).get('should_enter', False)
        if basic_should_enter:
            total_score += 10
            confluences.append("Timing de estructura básica óptimo")
        elif not basic_structure.get('entry_signal', {}).get('should_wait', True):
            total_score += 5
            confluences.append("Timing de estructura básica aceptable")
        
        # Calcular score final
        confluence_score = (total_score / max_possible_score) * 100 if max_possible_score > 0 else 0
        
        return {
            'score': confluence_score,
            'confluences': confluences,
            'total_score': total_score,
            'max_possible_score': max_possible_score,
            'individual_confidences': {
                'basic_structure': basic_confidence,
                'smart_money': smart_confidence,
                'learning_system': learning_confidence
            }
        }
    
    def _get_llm_timing_analysis(self, candles: pd.DataFrame, confluence_analysis: Dict, 
                               asset: str) -> Optional[Dict]:
        """Obtiene análisis de timing del LLM"""
        try:
            if not self.llm_client:
                return None
            
            # Preparar contexto para LLM
            context = self._prepare_llm_context(candles, confluence_analysis, asset)
            
            # Solicitar análisis
            llm_response = self.llm_client.analyze_entry_timing(
                df=candles,
                proposed_action=confluence_analysis.get('direction', 'HOLD'),
                proposed_asset=asset,
                extra_context=context
            )
            
            return llm_response
            
        except Exception as e:
            logger.error(f"Error en análisis LLM: {e}")
            return None
    
    def _prepare_llm_context(self, candles: pd.DataFrame, confluence_analysis: Dict, 
                           asset: str) -> str:
        """Prepara contexto para el LLM"""
        
        context_parts = [
            f"Asset: {asset}",
            f"Confluence Score: {confluence_analysis['score']:.1f}%",
            f"Confluences: {', '.join(confluence_analysis['confluences'][:3])}"
        ]
        
        # Agregar información técnica
        if not candles.empty:
            last_candle = candles.iloc[-1]
            if 'rsi' in candles.columns:
                context_parts.append(f"RSI: {last_candle['rsi']:.1f}")
            if 'macd' in candles.columns:
                context_parts.append(f"MACD: {last_candle['macd']:.5f}")
        
        return " | ".join(context_parts)
    
    def _generate_final_decision(self, confluence_analysis: Dict, learning_recommendation: Dict,
                               llm_timing_analysis: Optional[Dict], asset: str, 
                               current_balance: float) -> Dict:
        """Genera la decisión final de trading usando datos objetivos, NO parsing de texto"""
        
        decision = {
            'should_trade': False,
            'direction': None,
            'confidence': 0.0,
            'position_size': 0.0,
            'reasons': [],
            'warnings': [],
            'risk_assessment': {},
            'expected_outcome': {}
        }
        
        # 1. Verificar score mínimo de confluencia
        confluence_score = confluence_analysis['score']
        if confluence_score < self.min_confluence_score:
            decision['warnings'].append(f"Score de confluencia insuficiente ({confluence_score:.1f}% < {self.min_confluence_score}%)")
            return decision
        
        # 2. Verificar recomendación de aprendizaje
        if not learning_recommendation.get('should_trade', False):
            decision['warnings'].append("Sistema de aprendizaje no recomienda operar")
            return decision
        
        # 3. Determinar dirección usando DATOS OBJETIVOS (NO text-parsing)
        # Obtener dirección desde las fuentes de datos reales
        directions = []
        
        # Dirección desde smart_money_analysis (entry_signal)
        sm_entry = confluence_analysis.get('individual_confidences', {})
        if hasattr(self, 'smart_money_analyzer') and hasattr(self.smart_money_analyzer, 'last_direction'):
            sm_dir = self.smart_money_analyzer.last_direction
            if sm_dir in ['CALL', 'PUT']:
                directions.append(sm_dir)
        
        # Dirección desde basic_structure (entry_signal)
        if hasattr(self, 'market_structure_analyzer') and hasattr(self.market_structure_analyzer, 'last_direction'):
            ms_dir = self.market_structure_analyzer.last_direction
            if ms_dir in ['CALL', 'PUT']:
                directions.append(ms_dir)
        
        # Si no hay direcciones desde objetos, usar los reasons pero de forma estructurada
        if not directions:
            # Intentar obtener dirección desde el learning_recommendation
            learning_reasons = learning_recommendation.get('reasons', [])
            for reason in learning_reasons:
                if 'CALL' in reason.upper():
                    directions.append('CALL')
                elif 'PUT' in reason.upper():
                    directions.append('PUT')
        
        # Determinar dirección por mayoría
        if not directions:
            decision['warnings'].append("No se pudo determinar dirección clara")
            return decision
        
        call_votes = directions.count('CALL')
        put_votes = directions.count('PUT')
        
        if call_votes > put_votes:
            decision['direction'] = 'CALL'
        elif put_votes > call_votes:
            decision['direction'] = 'PUT'
        else:
            decision['warnings'].append("Empate en dirección - no hay consenso")
            return decision
        
        # 4. Calcular confianza final
        base_confidence = confluence_score / 100
        learning_confidence = learning_recommendation.get('confidence', 0)
        
        # Ajustar con LLM si disponible
        llm_adjustment = 0
        if llm_timing_analysis:
            if llm_timing_analysis.get('is_optimal', False):
                llm_adjustment = 0.1
            elif llm_timing_analysis.get('confidence', 0) > 0.7:
                llm_adjustment = 0.05
        
        final_confidence = min((base_confidence + learning_confidence) / 2 + llm_adjustment, 0.95)
        
        # 5. Verificar ventaja mínima
        if final_confidence < self.required_edge:
            decision['warnings'].append(f"Ventaja insuficiente ({final_confidence:.1%} < {self.required_edge:.1%})")
            return decision
        
        # 6. Calcular tamaño de posición
        risk_amount = current_balance * self.max_risk_per_trade
        
        # Ajustar por confianza
        confidence_multiplier = min(final_confidence / self.required_edge, 1.5)
        position_size = risk_amount * confidence_multiplier
        
        # 7. Completar decisión
        decision.update({
            'should_trade': True,
            'confidence': final_confidence,
            'position_size': position_size,
            'reasons': [
                f"Score de confluencia: {confluence_score:.1f}%",
                f"Confianza del aprendizaje: {learning_confidence:.1%}",
                f"Dirección consensuada: {decision['direction']}",
                f"Ventaja calculada: {final_confidence:.1%}"
            ],
            'risk_assessment': {
                'max_loss': risk_amount,
                'position_size_pct': (position_size / current_balance) * 100,
                'confidence_level': final_confidence,
                'risk_reward_expected': 0.85  # Payout típico de opciones binarias
            },
            'expected_outcome': {
                'win_probability': final_confidence,
                'expected_profit': position_size * 0.85 * final_confidence - position_size * (1 - final_confidence),
                'kelly_criterion': (final_confidence * 1.85 - 1) / 0.85  # Cálculo Kelly para opciones binarias
            }
        })
        
        # Agregar razones específicas
        decision['reasons'].extend(confluence_analysis['confluences'][:3])
        decision['reasons'].extend(learning_recommendation.get('reasons', [])[:2])
        
        return decision
    
    def _update_session_stats(self, final_decision: Dict, primary_concept: TradingConcept):
        """Actualiza estadísticas de la sesión"""
        
        if final_decision.get('should_trade', False):
            self.session_stats['signals_generated'] += 1
        
        # Tracking de conceptos usados
        concept_name = primary_concept.value
        if concept_name not in self.session_stats['concepts_used']:
            self.session_stats['concepts_used'][concept_name] = 0
        self.session_stats['concepts_used'][concept_name] += 1
        
        # Tracking de scores de confluencia
        confluence_score = final_decision.get('confluence_score', 0)
        self.session_stats['confluence_scores'].append(confluence_score)
    
    def _generate_error_response(self, error_message: str) -> Dict:
        """Genera respuesta de error"""
        return {
            'timestamp': datetime.now().isoformat(),
            'error': error_message,
            'final_decision': {
                'should_trade': False,
                'direction': None,
                'confidence': 0.0,
                'reasons': [],
                'warnings': [f"Error en análisis: {error_message}"]
            }
        }
    
    def process_trade_result(self, trade_data: Dict, market_analysis: Dict, result: Dict):
        """Procesa el resultado de una operación para aprendizaje"""
        try:
            # Agregar al sistema de aprendizaje profesional
            lesson = self.professional_learning.analyze_trade_for_learning(
                trade_data, market_analysis, result
            )
            
            if lesson:
                logger.info(f"Nueva lección aprendida: {lesson.concept.value} en {lesson.market_phase.value}")
            
        except Exception as e:
            logger.error(f"Error procesando resultado para aprendizaje: {e}")
    
    def get_session_summary(self) -> Dict:
        """Obtiene resumen de la sesión actual"""
        
        avg_confluence = np.mean(self.session_stats['confluence_scores']) if self.session_stats['confluence_scores'] else 0
        
        return {
            'total_analyses': self.session_stats['total_analyses'],
            'signals_generated': self.session_stats['signals_generated'],
            'signal_rate': (self.session_stats['signals_generated'] / max(self.session_stats['total_analyses'], 1)) * 100,
            'avg_confluence_score': avg_confluence,
            'most_used_concepts': sorted(
                self.session_stats['concepts_used'].items(), 
                key=lambda x: x[1], 
                reverse=True
            )[:3],
            'learning_insights': self.professional_learning.get_learning_insights()
        }
    
    def get_human_readable_analysis(self, analysis_result: Dict) -> str:
        """Convierte el análisis en texto legible"""
        
        if 'error' in analysis_result:
            return f"❌ Error: {analysis_result['error']}"
        
        lines = []
        lines.append("=" * 80)
        lines.append("🧠 ANÁLISIS INTELIGENTE DE TRADING")
        lines.append("=" * 80)
        
        # Información básica
        lines.append(f"\n📊 Asset: {analysis_result['asset']}")
        lines.append(f"🔄 Fase de Mercado: {analysis_result['market_phase'].upper()}")
        lines.append(f"🎯 Concepto Principal: {analysis_result['primary_concept'].upper()}")
        
        # Análisis de confluencias
        confluence = analysis_result['confluence_analysis']
        lines.append(f"\n⚖️ SCORE DE CONFLUENCIA: {confluence['score']:.1f}%")
        
        if confluence['confluences']:
            lines.append("\nConfluencias detectadas:")
            for conf in confluence['confluences']:
                lines.append(f"  ✓ {conf}")
        
        # Recomendación de aprendizaje
        learning = analysis_result['learning_recommendation']
        lines.append(f"\n🎓 APRENDIZAJE PROFESIONAL:")
        lines.append(f"   Recomendación: {'✅ OPERAR' if learning['should_trade'] else '⏸️ ESPERAR'}")
        lines.append(f"   Confianza: {learning['confidence']:.1%}")
        
        if learning['reasons']:
            lines.append("   Razones:")
            for reason in learning['reasons'][:3]:
                lines.append(f"     • {reason}")
        
        # Decisión final
        decision = analysis_result['final_decision']
        lines.append("\n" + "=" * 80)
        lines.append("🎯 DECISIÓN FINAL")
        lines.append("=" * 80)
        
        if decision['should_trade']:
            lines.append(f"✅ EJECUTAR {decision['direction']} - Confianza: {decision['confidence']:.1%}")
            lines.append(f"💰 Tamaño de posición: ${decision['position_size']:.2f}")
            
            if decision['reasons']:
                lines.append("\nRazones principales:")
                for reason in decision['reasons'][:4]:
                    lines.append(f"  ✓ {reason}")
            
            # Risk assessment
            risk = decision.get('risk_assessment', {})
            if risk:
                lines.append(f"\n📊 Evaluación de Riesgo:")
                lines.append(f"   Pérdida máxima: ${risk.get('max_loss', 0):.2f}")
                lines.append(f"   % de cuenta: {risk.get('position_size_pct', 0):.1f}%")
        
        else:
            lines.append("⏸️ NO OPERAR - Condiciones no favorables")
            
            if decision['warnings']:
                lines.append("\nAdvertencias:")
                for warning in decision['warnings']:
                    lines.append(f"  ⚠️ {warning}")
        
        lines.append("=" * 80)
        return "\n".join(lines)