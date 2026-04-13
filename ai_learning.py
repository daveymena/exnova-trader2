"""
🧠 SISTEMA DE IA PARA TRADING - APRENDIZAJE PROGRESIVO
Maneja operaciones, aprende de pérdidas y refina entradas
"""
import json
import os
import time
from datetime import datetime
from pathlib import Path


class TradingLearner:
    """
    Sistema de aprendizaje que:
    1. Guarda historial de operaciones
    2. Detecta patrones de pérdida
    3. Refina criterios de entrada
    4. Evita operaciones simultáneas
    """

    def __init__(self, data_dir="data/ai_learning"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Archivos de datos
        self.history_file = self.data_dir / "operation_history.json"
        self.patterns_file = self.data_dir / "loss_patterns.json"
        self.lock_file = self.data_dir / "operation.lock"
        self.config_file = self.data_dir / "config.json"

        # Estado
        self.operations = []
        self.loss_patterns = {}
        self.active_trade = None
        self.consecutive_losses = 0
        self.max_consecutive_losses = 3  # 🛑 Parar después de 3 pérdidas seguidas
        self.cooldown_until = 0
        self.cooldown_duration = 300  # 5 minutos de pausa tras pérdida

        # Umbral de confianza adaptativo
        self.base_threshold = 70.0
        self.current_threshold = self.base_threshold

        # Cargar datos existentes
        self._load_data()

    def _load_data(self):
        """Carga historial y patrones"""
        # Cargar operaciones
        if self.history_file.exists():
            try:
                with open(self.history_file, 'r') as f:
                    self.operations = json.load(f)
                print(f"✅ Historial cargado: {len(self.operations)} operaciones")
            except Exception as e:
                print(f"⚠️ Error cargando historial: {e}")
                self.operations = []

        # Cargar patrones de pérdida
        if self.patterns_file.exists():
            try:
                with open(self.patterns_file, 'r') as f:
                    self.loss_patterns = json.load(f)
                print(f"✅ Patrones de pérdida cargados")
            except Exception as e:
                print(f"⚠️ Error cargando patrones: {e}")
                self.loss_patterns = {}

        # Cargar configuración
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r') as f:
                    config = json.load(f)
                    self.current_threshold = config.get('threshold', self.base_threshold)
                    self.consecutive_losses = config.get('consecutive_losses', 0)
            except:
                pass

    def _save_data(self):
        """Guarda historial y patrones"""
        try:
            with open(self.history_file, 'w') as f:
                json.dump(self.operations, f, indent=2, default=str)

            with open(self.patterns_file, 'w') as f:
                json.dump(self.loss_patterns, f, indent=2)

            with open(self.config_file, 'w') as f:
                json.dump({
                    'threshold': self.current_threshold,
                    'consecutive_losses': self.consecutive_losses,
                    'last_updated': datetime.now().isoformat()
                }, f, indent=2)
        except Exception as e:
            print(f"⚠️ Error guardando datos: {e}")

    def is_operation_in_progress(self):
        """
        🚨 VERIFICA SI HAY UNA OPERACIÓN EN CURSO
        Previene operaciones simultáneas
        """
        if self.lock_file.exists():
            try:
                with open(self.lock_file, 'r') as f:
                    lock_data = json.load(f)
                    lock_time = lock_data.get('timestamp', 0)
                    # Si el lock tiene más de 15 minutos, es stale
                    if time.time() - lock_time > 900:  # 15 minutos
                        self._release_lock()
                        return False
                    return True
            except:
                return False
        return False

    def _acquire_lock(self, operation_data):
        """Marca que hay una operación activa"""
        try:
            with open(self.lock_file, 'w') as f:
                json.dump({
                    'timestamp': time.time(),
                    'asset': operation_data.get('asset'),
                    'direction': operation_data.get('direction'),
                    'started_at': datetime.now().isoformat()
                }, f)
            self.active_trade = operation_data
        except Exception as e:
            print(f"⚠️ Error creando lock: {e}")

    def _release_lock(self):
        """Libera el lock de operación"""
        try:
            if self.lock_file.exists():
                self.lock_file.unlink()
            self.active_trade = None
        except Exception as e:
            print(f"⚠️ Error liberando lock: {e}")

    def should_enter_trade(self, context):
        """
        🧠 DECIDE SI ENTRAR O NO EN UNA OPERACIÓN
        Considera: historial, pérdidas recientes, cooldowns
        """
        asset = context.get('asset')
        direction = context.get('direction')
        rsi = context.get('rsi', 50)

        # 1. Verificar operación en curso
        if self.is_operation_in_progress():
            return False, "⛔ RECHAZADO: Ya hay una operación en curso"

        # 2. Verificar cooldown por pérdidas
        if time.time() < self.cooldown_until:
            remaining = int(self.cooldown_until - time.time())
            return False, f"⛔ RECHAZADO: En cooldown por pérdida ({remaining}s restantes)"

        # 3. Verificar límite de pérdidas consecutivas
        if self.consecutive_losses >= self.max_consecutive_losses:
            return False, f"⛔ RECHAZADO: Límite de {self.max_consecutive_losses} pérdidas consecutivas alcanzado"

        # 4. Verificar si este patrón ha fallado antes
        pattern_key = f"{asset}_{direction}_RSI{int(rsi/5)*5}"  # Agrupar RSI en rangos de 5
        if pattern_key in self.loss_patterns:
            failures = self.loss_patterns[pattern_key].get('failures', 0)
            if failures >= 3:
                return False, f"⛔ RECHAZADO: Patrón {pattern_key} ha fallado {failures} veces"

        # 5. Analizar historial del activo
        asset_stats = self._get_asset_stats(asset)
        if asset_stats['total'] >= 5:
            win_rate = asset_stats['wins'] / asset_stats['total']
            if win_rate < 0.4:  # Menos de 40% de aciertos en este activo
                return False, f"⛔ RECHAZADO: Win rate del activo muy bajo ({win_rate:.1%})"

        # ✅ Aprobado
        return True, f"✅ APROBADO: Confianza adaptativa {self.current_threshold:.1f}%"

    def record_operation(self, operation_data):
        """
        📝 REGISTRA UNA NUEVA OPERACIÓN Y APRENDE
        """
        # Agregar metadatos
        operation_data['recorded_at'] = datetime.now().isoformat()
        operation_data['id'] = len(self.operations) + 1

        # Guardar en historial
        self.operations.append(operation_data)

        # Acquired lock al abrir operación
        self._acquire_lock(operation_data)

        # Guardar datos
        self._save_data()

        print(f"   📝 Operación #{operation_data['id']} registrada para aprendizaje")

    def analyze_operation(self, operation_data):
        """
        🔍 ANALIZA EL RESULTADO Y AJUSTA ESTRATEGIA
        Llamar después de que cierra la operación
        """
        result = operation_data.get('result', 'UNKNOWN')
        asset = operation_data.get('asset')
        direction = operation_data.get('direction')
        rsi = operation_data.get('rsi', 50)
        movement = operation_data.get('movement', 0)

        # Liberar lock
        self._release_lock()

        analysis = {
            'pattern_detected': None,
            'why_won_or_lost': None,
            'suggestion': None,
            'adjustments_made': []
        }

        if result == 'WIN':
            # Resetear pérdidas consecutivas
            self.consecutive_losses = 0
            self.cooldown_until = 0

            # Subir umbral gradualmente (más selectivo)
            self.current_threshold = min(85, self.current_threshold + 1)

            analysis['why_won_or_lost'] = f"✅ Acertado: Movimiento {movement:+.4f}% a favor"
            analysis['suggestion'] = "Continuar con estrategia actual"

        elif result == 'LOSS':
            # Incrementar pérdidas consecutivas
            self.consecutive_losses += 1

            # Activar cooldown
            self.cooldown_until = time.time() + self.cooldown_duration

            # Registrar patrón de pérdida
            pattern_key = f"{asset}_{direction}_RSI{int(rsi/5)*5}"
            if pattern_key not in self.loss_patterns:
                self.loss_patterns[pattern_key] = {'failures': 0, 'last_failure': None}
            self.loss_patterns[pattern_key]['failures'] += 1
            self.loss_patterns[pattern_key]['last_failure'] = datetime.now().isoformat()

            # Bajar umbral (más conservador)
            self.current_threshold = max(60, self.current_threshold - 2)

            # Analizar por qué perdimos
            analysis['pattern_detected'] = pattern_key
            analysis['why_won_or_lost'] = f"❌ Perdida: Movimiento {movement:+.4f}% en contra"

            # Sugerencias específicas
            if abs(movement) > 0.5:
                analysis['suggestion'] = "⚠️ Movimiento fuerte en contra - Revisar confirmación de tendencia"
            elif self.consecutive_losses >= 2:
                analysis['suggestion'] = f"🛑 {self.consecutive_losses} pérdidas seguidas - Considerar pausa"
            else:
                analysis['suggestion'] = "🔄 Ajustar timing de entrada"

            analysis['adjustments_made'] = [
                f"Umbral ajustado a {self.current_threshold:.1f}%",
                f"Cooldown activado: {self.cooldown_duration}s",
                f"Pérdidas consecutivas: {self.consecutive_losses}"
            ]

        # Guardar cambios
        self._save_data()

        return analysis

    def _get_asset_stats(self, asset):
        """Calcula estadísticas de un activo"""
        asset_ops = [op for op in self.operations if op.get('asset') == asset]
        wins = len([op for op in asset_ops if op.get('result') == 'WIN'])
        return {
            'total': len(asset_ops),
            'wins': wins,
            'losses': len(asset_ops) - wins
        }

    def get_improvement_suggestions(self):
        """
        💡 GENERA SUGERENCIAS BASADAS EN EL HISTORIAL
        """
        suggestions = []

        if not self.operations:
            return ["No hay operaciones suficientes para analizar"]

        total = len(self.operations)
        wins = len([op for op in self.operations if op.get('result') == 'WIN'])
        win_rate = wins / total if total > 0 else 0

        # Análisis general
        if win_rate < 0.5:
            suggestions.append(f"📉 Win rate bajo ({win_rate:.1%}). Considerar:")
            suggestions.append("   - Aumentar confirmación de velas requeridas")
            suggestions.append("   - Reducir tamaño de posición")
            suggestions.append("   - Esperar mejor timing")

        elif win_rate > 0.65:
            suggestions.append(f"📈 Buen win rate ({win_rate:.1%})! Considerar:")
            suggestions.append("   - Aumentar ligeramente el capital por trade")
            suggestions.append("   - Buscar más oportunidades similares")

        # Patrones problemáticos
        problematic = {k: v for k, v in self.loss_patterns.items() if v.get('failures', 0) >= 2}
        if problematic:
            suggestions.append(f"⚠️ {len(problematic)} patrones problemáticos detectados:")
            for pattern, data in list(problematic.items())[:3]:
                suggestions.append(f"   - {pattern}: {data['failures']} fallos")

        # Mejores activos
        asset_performance = {}
        for op in self.operations:
            asset = op.get('asset')
            if asset not in asset_performance:
                asset_performance[asset] = {'wins': 0, 'total': 0}
            asset_performance[asset]['total'] += 1
            if op.get('result') == 'WIN':
                asset_performance[asset]['wins'] += 1

        if asset_performance:
            best_asset = max(asset_performance.items(),
                           key=lambda x: x[1]['wins']/x[1]['total'] if x[1]['total'] > 0 else 0)
            if best_asset[1]['total'] >= 3:
                win_rate_best = best_asset[1]['wins'] / best_asset[1]['total']
                suggestions.append(f"🏆 Mejor activo: {best_asset[0]} ({win_rate_best:.0%} WR en {best_asset[1]['total']} ops)")

        return suggestions if suggestions else ["Continuar monitoreando..."]

    def get_status(self):
        """Retorna estado actual del sistema de IA"""
        total = len(self.operations)
        wins = len([op for op in self.operations if op.get('result') == 'WIN'])
        win_rate = (wins / total * 100) if total > 0 else 0

        status = f"""
🧠 ESTADO DEL SISTEMA DE IA:
   Operaciones registradas: {total}
   Ganadas: {wins} | Perdidas: {total - wins}
   Win Rate: {win_rate:.1f}%
   Umbral actual: {self.current_threshold:.1f}%
   Pérdidas consecutivas: {self.consecutive_losses}/{self.max_consecutive_losses}
   Cooldown activo: {'Sí' if time.time() < self.cooldown_until else 'No'}
   Operación en curso: {'Sí' if self.is_operation_in_progress() else 'No'}
        """
        return status


def create_learner():
    """Factory function para crear el learner"""
    return TradingLearner()


# Test
if __name__ == "__main__":
    print("🧠 Probando sistema de IA...")
    learner = create_learner()
    print(learner.get_status())
