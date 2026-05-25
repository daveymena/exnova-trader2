"""
🔍 DETECTOR DE INCOHERENCIAS
Detecta errores lógicos en entradas:
- Comprar en resistencia cuando debe ser en soporte
- Vender en soporte cuando debe ser en resistencia
- Entradas en zonas débiles
- Patrones contradictorios
"""
import json
from typing import Dict, List, Optional, Tuple
from pathlib import Path


class IncoherenceDetector:
    """
    Detecta incoherencias en la lógica de trading
    """

    def __init__(self, trade_history_file: str = "bot/brain/trade_history.json"):
        self.name = "Incoherence Detector v1.0"
        self.version = "1.0"
        self.trade_history_file = Path(trade_history_file)
        
        # Datos
        self.trades = []
        self.incoherences_found = []
        self.corrections_suggested = []
        
        print(f"[OK] {self.name} inicializado")
        self._load_trades()

    # ═══════════════════════════════════════════════════════════════════════════════
    # CARGA DE DATOS
    # ═══════════════════════════════════════════════════════════════════════════════

    def _load_trades(self) -> None:
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

    # ═══════════════════════════════════════════════════════════════════════════════
    # DETECCIÓN DE INCOHERENCIAS
    # ═══════════════════════════════════════════════════════════════════════════════

    def detect_all_incoherences(self) -> List[Dict]:
        """
        Detecta todas las incoherencias en los trades
        """
        print(f"\n[*] Analizando {len(self.trades)} trades para detectar incoherencias...")
        
        self.incoherences_found = []
        
        for i, trade in enumerate(self.trades):
            incoherence = self._analyze_trade(trade, i)
            if incoherence:
                self.incoherences_found.append(incoherence)
        
        print(f"[OK] {len(self.incoherences_found)} incoherencias detectadas")
        return self.incoherences_found

    def _analyze_trade(self, trade: Dict, index: int) -> Optional[Dict]:
        """
        Analiza un trade individual para detectar incoherencias
        """
        
        incoherence = None
        
        # Extraer datos
        asset = trade.get('asset', 'UNKNOWN')
        direction = trade.get('direction', 'UNKNOWN')
        zone = trade.get('zone', 'unknown')
        zone_type = trade.get('zone_type', 'unknown')
        result = trade.get('result', 'UNKNOWN')
        pnl = trade.get('pnl', 0)
        pattern = trade.get('pattern', 'none')
        rsi = trade.get('rsi_at_touch', 50)
        
        # ─────────────────────────────────────────────────────────────────────────
        # INCOHERENCIA 1: Dirección vs Zona
        # ─────────────────────────────────────────────────────────────────────────
        
        if zone_type == 'resistance' and direction == 'CALL':
            # Comprar en resistencia es incorrecto
            incoherence = {
                'trade_index': index,
                'asset': asset,
                'type': 'WRONG_DIRECTION_FOR_ZONE',
                'severity': 'HIGH',
                'description': f"COMPRA en RESISTENCIA (zona {zone})",
                'current': f"Direction: {direction}, Zone: {zone_type}",
                'should_be': "Direction: PUT (vender en resistencia)",
                'result': result,
                'pnl': pnl,
                'pattern': pattern,
                'rsi': rsi
            }
        
        elif zone_type == 'support' and direction == 'PUT':
            # Vender en soporte es incorrecto
            incoherence = {
                'trade_index': index,
                'asset': asset,
                'type': 'WRONG_DIRECTION_FOR_ZONE',
                'severity': 'HIGH',
                'description': f"VENTA en SOPORTE (zona {zone})",
                'current': f"Direction: {direction}, Zone: {zone_type}",
                'should_be': "Direction: CALL (comprar en soporte)",
                'result': result,
                'pnl': pnl,
                'pattern': pattern,
                'rsi': rsi
            }
        
        # ─────────────────────────────────────────────────────────────────────────
        # INCOHERENCIA 2: RSI extremo pero dirección incorrecta
        # ─────────────────────────────────────────────────────────────────────────
        
        elif rsi < 30 and direction == 'PUT':
            # RSI bajo (sobreventa) pero vender es incorrecto
            incoherence = {
                'trade_index': index,
                'asset': asset,
                'type': 'RSI_DIRECTION_MISMATCH',
                'severity': 'MEDIUM',
                'description': f"RSI {rsi} indica sobreventa pero se VENDE",
                'current': f"RSI: {rsi} (sobreventa), Direction: {direction}",
                'should_be': "Direction: CALL (comprar en sobreventa)",
                'result': result,
                'pnl': pnl,
                'pattern': pattern,
                'rsi': rsi
            }
        
        elif rsi > 70 and direction == 'CALL':
            # RSI alto (sobrecompra) pero comprar es incorrecto
            incoherence = {
                'trade_index': index,
                'asset': asset,
                'type': 'RSI_DIRECTION_MISMATCH',
                'severity': 'MEDIUM',
                'description': f"RSI {rsi} indica sobrecompra pero se COMPRA",
                'current': f"RSI: {rsi} (sobrecompra), Direction: {direction}",
                'should_be': "Direction: PUT (vender en sobrecompra)",
                'result': result,
                'pnl': pnl,
                'pattern': pattern,
                'rsi': rsi
            }
        
        # ─────────────────────────────────────────────────────────────────────────
        # INCOHERENCIA 3: Patrón débil
        # ─────────────────────────────────────────────────────────────────────────
        
        elif pattern == 'none' and result == 'BREAK':
            # Sin patrón específico y perdió
            incoherence = {
                'trade_index': index,
                'asset': asset,
                'type': 'WEAK_PATTERN',
                'severity': 'MEDIUM',
                'description': f"Sin patrón específico - PÉRDIDA",
                'current': f"Pattern: {pattern}, Result: {result}",
                'should_be': "Requerir patrón específico (confianza > 0.65)",
                'result': result,
                'pnl': pnl,
                'pattern': pattern,
                'rsi': rsi
            }
        
        return incoherence

    # ═══════════════════════════════════════════════════════════════════════════════
    # ANÁLISIS POR TIPO DE INCOHERENCIA
    # ═══════════════════════════════════════════════════════════════════════════════

    def get_incoherences_by_type(self) -> Dict[str, List[Dict]]:
        """Agrupa incoherencias por tipo"""
        
        by_type = {}
        for incoherence in self.incoherences_found:
            inc_type = incoherence['type']
            if inc_type not in by_type:
                by_type[inc_type] = []
            by_type[inc_type].append(incoherence)
        
        return by_type

    def get_incoherences_by_asset(self) -> Dict[str, List[Dict]]:
        """Agrupa incoherencias por activo"""
        
        by_asset = {}
        for incoherence in self.incoherences_found:
            asset = incoherence['asset']
            if asset not in by_asset:
                by_asset[asset] = []
            by_asset[asset].append(incoherence)
        
        return by_asset

    def get_incoherences_by_severity(self) -> Dict[str, List[Dict]]:
        """Agrupa incoherencias por severidad"""
        
        by_severity = {}
        for incoherence in self.incoherences_found:
            severity = incoherence['severity']
            if severity not in by_severity:
                by_severity[severity] = []
            by_severity[severity].append(incoherence)
        
        return by_severity

    # ═══════════════════════════════════════════════════════════════════════════════
    # GENERACIÓN DE CORRECCIONES
    # ═══════════════════════════════════════════════════════════════════════════════

    def generate_corrections(self) -> List[Dict]:
        """
        Genera correcciones sugeridas basadas en incoherencias
        """
        print(f"\n[*] Generando correcciones...")
        
        self.corrections_suggested = []
        
        # Agrupar por tipo
        by_type = self.get_incoherences_by_type()
        
        # Corrección 1: Dirección vs Zona
        if 'WRONG_DIRECTION_FOR_ZONE' in by_type:
            incs = by_type['WRONG_DIRECTION_FOR_ZONE']
            self.corrections_suggested.append({
                'type': 'LOGIC_FIX',
                'priority': 'CRITICAL',
                'issue': f"{len(incs)} trades con dirección incorrecta para la zona",
                'fix': "Invertir lógica: Support=CALL, Resistance=PUT",
                'expected_impact': f"Reducir pérdidas en ~{len(incs)} trades",
                'implementation': """
                if zone_type == 'support':
                    direction = 'CALL'  # Comprar en soporte
                elif zone_type == 'resistance':
                    direction = 'PUT'   # Vender en resistencia
                """
            })
        
        # Corrección 2: RSI
        if 'RSI_DIRECTION_MISMATCH' in by_type:
            incs = by_type['RSI_DIRECTION_MISMATCH']
            self.corrections_suggested.append({
                'type': 'LOGIC_FIX',
                'priority': 'HIGH',
                'issue': f"{len(incs)} trades con RSI contradictorio",
                'fix': "Respetar extremos de RSI: RSI<30=CALL, RSI>70=PUT",
                'expected_impact': f"Mejorar WR en ~{len(incs)} trades",
                'implementation': """
                if rsi < 30:
                    direction = 'CALL'  # Sobreventa
                elif rsi > 70:
                    direction = 'PUT'   # Sobrecompra
                """
            })
        
        # Corrección 3: Patrón débil
        if 'WEAK_PATTERN' in by_type:
            incs = by_type['WEAK_PATTERN']
            self.corrections_suggested.append({
                'type': 'VALIDATION_FIX',
                'priority': 'HIGH',
                'issue': f"{len(incs)} trades sin patrón específico",
                'fix': "Requerir patrón con confianza > 0.65",
                'expected_impact': f"Evitar {len(incs)} trades débiles",
                'implementation': """
                if pattern == 'none' or pattern_confidence < 0.65:
                    skip_trade()  # No tradear sin patrón fuerte
                """
            })
        
        print(f"[OK] {len(self.corrections_suggested)} correcciones generadas")
        return self.corrections_suggested

    # ═══════════════════════════════════════════════════════════════════════════════
    # REPORTES
    # ═══════════════════════════════════════════════════════════════════════════════

    def generate_report(self) -> str:
        """Genera reporte de incoherencias"""
        
        report = f"""
╔════════════════════════════════════════════════════════════════════════════════╗
║                    🔍 REPORTE DE INCOHERENCIAS                                ║
╚════════════════════════════════════════════════════════════════════════════════╝

📊 RESUMEN:
  • Total de trades analizados: {len(self.trades)}
  • Incoherencias detectadas: {len(self.incoherences_found)}
  • Porcentaje: {len(self.incoherences_found)/len(self.trades)*100:.1f}%

🔴 INCOHERENCIAS POR SEVERIDAD:
"""
        
        by_severity = self.get_incoherences_by_severity()
        for severity in ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW']:
            if severity in by_severity:
                count = len(by_severity[severity])
                report += f"  • {severity}: {count}\n"
        
        report += f"""
🔴 INCOHERENCIAS POR TIPO:
"""
        
        by_type = self.get_incoherences_by_type()
        for inc_type, incs in by_type.items():
            report += f"  • {inc_type}: {len(incs)}\n"
        
        report += f"""
🔴 INCOHERENCIAS POR ACTIVO:
"""
        
        by_asset = self.get_incoherences_by_asset()
        for asset, incs in sorted(by_asset.items(), key=lambda x: len(x[1]), reverse=True):
            report += f"  • {asset}: {len(incs)}\n"
        
        report += f"""
✅ CORRECCIONES SUGERIDAS:
"""
        
        for i, correction in enumerate(self.corrections_suggested, 1):
            report += f"""
  [{i}] {correction['type']} - {correction['priority']}
      Problema: {correction['issue']}
      Solución: {correction['fix']}
      Impacto: {correction['expected_impact']}
"""
        
        report += f"""
{'='*80}
"""
        
        return report

    def get_summary(self) -> Dict:
        """Resumen del detector"""
        return {
            'name': self.name,
            'version': self.version,
            'trades_analyzed': len(self.trades),
            'incoherences_found': len(self.incoherences_found),
            'corrections_suggested': len(self.corrections_suggested),
            'status': 'ACTIVE'
        }


# Singleton
_detector: Optional[IncoherenceDetector] = None


def get_incoherence_detector() -> IncoherenceDetector:
    global _detector
    if _detector is None:
        _detector = IncoherenceDetector()
    return _detector


if __name__ == "__main__":
    detector = get_incoherence_detector()
    
    # Detectar incoherencias
    incoherences = detector.detect_all_incoherences()
    
    # Generar correcciones
    corrections = detector.generate_corrections()
    
    # Mostrar reporte
    print(detector.generate_report())
