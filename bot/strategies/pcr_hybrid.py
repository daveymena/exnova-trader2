"""
PCR Hybrid - Estrategia híbrida que combina PCR Simple + Complete + Validadores
Sistema integrado listo para producción
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional

from .pcr_simple import PCRSimple
from .pcr_complete import PCRComplete
from .pcr_validator_gates import PCRValidatorGates


class PCRHybrid:
    """
    Estrategia híbrida que:
    1. Genera señales de PCR Simple + Complete
    2. Las valida con 8 porteros
    3. Las combina con lógica inteligente
    4. Retorna decisión final con alta confianza
    """

    def __init__(self, mode='balanced'):
        """
        Args:
            mode: 'aggressive' (Simple priority), 'conservative' (Complete priority), 'balanced'
        """
        self.mode = mode
        self.pcr_simple = PCRSimple()
        self.pcr_complete = PCRComplete()
        self.validator = PCRValidatorGates()

        # Estadísticas de desempeño
        self.stats = {
            'total_signals': 0,
            'approved_signals': 0,
            'rejected_signals': 0,
            'consensus_signals': 0,
            'conflicting_signals': 0
        }

    def analyze(self, df: pd.DataFrame, df_higher_tf: Optional[pd.DataFrame] = None,
                asset_name: str = None, strict: bool = False) -> Dict:
        """
        Análisis completo híbrido

        Args:
            df: DataFrame con OHLCV
            df_higher_tf: DataFrame de timeframe superior (opcional)
            asset_name: Nombre del activo
            strict: Si True, requiere validación 100%

        Returns:
            dict con análisis y decisión final
        """
        # Generar análisis individuales
        simple_analysis = self.pcr_simple.analyze(df, asset_name)
        complete_analysis = self.pcr_complete.analyze(df, df_higher_tf, asset_name)

        result = {
            'timestamp': df.iloc[-1].get('timestamp') if 'timestamp' in df.columns else None,
            'close': float(df.iloc[-1]['close']),
            'asset': asset_name,

            # Análisis individuales
            'simple': {
                'signal': simple_analysis.get('signal'),
                'confidence': simple_analysis.get('confidence'),
                'approved': False,
                'validation': None
            },
            'complete': {
                'signal': complete_analysis.get('signal'),
                'confidence': complete_analysis.get('confidence'),
                'approved': False,
                'validation': None
            },

            # Decisión híbrida
            'hybrid': {
                'signal': None,
                'confidence': 0,
                'consensus': False,
                'methodology': None,
                'reasons': []
            },

            # Metadatos
            'mode': self.mode,
            'strict': strict
        }

        # Validar cada análisis con porteros
        simple_valid, simple_validation = self.validator.validate_signal(
            simple_analysis, df, strict=strict
        )
        result['simple']['approved'] = simple_valid
        result['simple']['validation'] = simple_validation

        complete_valid, complete_validation = self.validator.validate_signal(
            complete_analysis, df, strict=strict
        )
        result['complete']['approved'] = complete_valid
        result['complete']['validation'] = complete_validation

        # Generar decisión híbrida
        hybrid_decision = self._combine_strategies(
            simple_analysis, simple_valid,
            complete_analysis, complete_valid,
            df
        )

        result['hybrid'] = hybrid_decision

        return result

    def _combine_strategies(self, simple: Dict, simple_valid: bool,
                          complete: Dict, complete_valid: bool,
                          df: pd.DataFrame) -> Dict:
        """
        Combina estrategias simple y complete de forma inteligente
        """
        hybrid = {
            'signal': None,
            'confidence': 0,
            'consensus': False,
            'methodology': None,
            'reasons': []
        }

        simple_signal = simple.get('signal')
        simple_conf = simple.get('confidence', 0)
        complete_signal = complete.get('signal')
        complete_conf = complete.get('confidence', 0)

        # Caso 1: CONSENSO - Ambas estrategias aprueban la MISMA señal
        if simple_valid and complete_valid and simple_signal and complete_signal:
            if simple_signal == complete_signal:
                hybrid['consensus'] = True
                hybrid['signal'] = simple_signal
                hybrid['confidence'] = min(100, (simple_conf + complete_conf) / 2 + 15)  # +15 por consenso
                hybrid['methodology'] = 'CONSENSUS'
                hybrid['reasons'].append(f"✓ CONSENSO: Ambas estrategias generan {simple_signal}")
                hybrid['reasons'].append(f"  Simple: {simple_conf}% | Complete: {complete_conf}%")
                return hybrid

        # Caso 2: CONFLICTO - Estrategias generan señales opuestas
        if simple_valid and complete_valid and simple_signal and complete_signal:
            if simple_signal != complete_signal:
                # Preferir la más confiable
                if simple_conf > complete_conf:
                    hybrid['signal'] = simple_signal
                    hybrid['confidence'] = simple_conf - 10  # -10 por conflicto
                    hybrid['methodology'] = 'CONFLICT_SIMPLE_PREFERRED'
                    hybrid['reasons'].append(f"⚠️  CONFLICTO: Simple({simple_conf}%) vs Complete({complete_conf}%)")
                    hybrid['reasons'].append(f"  Usando Simple por mayor confianza")
                else:
                    hybrid['signal'] = complete_signal
                    hybrid['confidence'] = complete_conf - 10
                    hybrid['methodology'] = 'CONFLICT_COMPLETE_PREFERRED'
                    hybrid['reasons'].append(f"⚠️  CONFLICTO: Complete({complete_conf}%) vs Simple({simple_conf}%)")
                    hybrid['reasons'].append(f"  Usando Complete por mayor confianza")
                return hybrid

        # Caso 3: SIMPLE APROBADA - Complete no apruebanra pero Simple sí
        if simple_valid and simple_signal and not complete_valid:
            hybrid['signal'] = simple_signal
            hybrid['confidence'] = simple_conf - 5  # -5 por falta de validación complete
            hybrid['methodology'] = 'SIMPLE_ONLY'
            hybrid['reasons'].append(f"Simple válida: {simple_signal} @ {simple_conf}%")
            hybrid['reasons'].append(f"Complete rechazada: validación insuficiente")
            return hybrid

        # Caso 4: COMPLETE APROBADA - Simple no aprueba pero Complete sí
        if complete_valid and complete_signal and not simple_valid:
            hybrid['signal'] = complete_signal
            hybrid['confidence'] = complete_conf - 5
            hybrid['methodology'] = 'COMPLETE_ONLY'
            hybrid['reasons'].append(f"Complete válida: {complete_signal} @ {complete_conf}%")
            hybrid['reasons'].append(f"Simple rechazada: validación insuficiente")
            return hybrid

        # Caso 5: NINGUNA APROBADA
        hybrid['signal'] = None
        hybrid['confidence'] = 0
        hybrid['methodology'] = 'REJECTED'
        hybrid['reasons'].append("Ambas estrategias rechazadas por porteros")
        if not simple_valid:
            hybrid['reasons'].append(f"  Simple: confianza {simple_conf}% insuficiente")
        if not complete_valid:
            hybrid['reasons'].append(f"  Complete: confianza {complete_conf}% insuficiente")

        return hybrid

    def get_recommended_entry_time(self) -> int:
        """Tiempo de entrada recomendado en segundos"""
        # Hybrid: espera validación del híbrido
        return 90  # 1.5 minutos

    def get_recommended_expiry_time(self) -> int:
        """Tiempo de expiración recomendado en segundos"""
        # Hybrid: medio-largo plazo (validación de estructura)
        return 240  # 4 minutos

    def get_stats(self) -> Dict:
        """Retorna estadísticas de desempeño"""
        return {
            'total_signals': self.stats['total_signals'],
            'approved': self.stats['approved_signals'],
            'rejected': self.stats['rejected_signals'],
            'consensus': self.stats['consensus_signals'],
            'conflicts': self.stats['conflicting_signals'],
            'approval_rate': round(
                (self.stats['approved_signals'] / self.stats['total_signals'] * 100)
                if self.stats['total_signals'] > 0 else 0,
                1
            ),
            'consensus_rate': round(
                (self.stats['consensus_signals'] / self.stats['approved_signals'] * 100)
                if self.stats['approved_signals'] > 0 else 0,
                1
            )
        }

    def print_analysis(self, result: Dict):
        """Imprime análisis detallado"""
        print(f"\n{'='*80}")
        print(f"🎯 PCR HYBRID ANALYSIS - {result['asset']}")
        print(f"{'='*80}")

        # Estado Simple
        print(f"\n📊 PCR SIMPLE")
        print(f"{'-'*40}")
        simple = result['simple']
        print(f"  Señal: {simple['signal'] or 'NINGUNA'}")
        print(f"  Confianza: {simple['confidence']}%")
        print(f"  Estado: {'✅ APROBADA' if simple['approved'] else '❌ RECHAZADA'}")

        # Estado Complete
        print(f"\n📊 PCR COMPLETE")
        print(f"{'-'*40}")
        complete = result['complete']
        print(f"  Señal: {complete['signal'] or 'NINGUNA'}")
        print(f"  Confianza: {complete['confidence']}%")
        print(f"  Estado: {'✅ APROBADA' if complete['approved'] else '❌ RECHAZADA'}")

        # Decisión Híbrida
        print(f"\n🚀 DECISIÓN HÍBRIDA")
        print(f"{'-'*40}")
        hybrid = result['hybrid']
        print(f"  Metodología: {hybrid['methodology']}")
        print(f"  Consenso: {'✓ SÍ' if hybrid['consensus'] else '✗ NO'}")
        print(f"  Señal FINAL: {hybrid['signal'] or 'RECHAZADA'}")
        print(f"  Confianza FINAL: {hybrid['confidence']}%")

        if hybrid['reasons']:
            print(f"\n💡 Razones:")
            for reason in hybrid['reasons']:
                print(f"   {reason}")

        print(f"\n{'='*80}")
