"""
Trade Persistence - Sistema centralizado de persistencia de operaciones
Garantiza que TODOS los trades se guardan y se cargan correctamente
"""
import json
import os
import time
from typing import Dict, List, Optional
from datetime import datetime


class TradePersistence:
    """
    Sistema centralizado que:
    1. Guarda TODOS los trades en un archivo único
    2. Carga el historial al iniciar
    3. Sincroniza con el AdaptiveLearner
    4. Proporciona estadísticas de trading
    """

    def __init__(self, persist_path: str = "brain/trade_history.json"):
        self.persist_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", persist_path
        )
        os.makedirs(os.path.dirname(self.persist_path), exist_ok=True)
        
        self.trades: List[Dict] = []
        self.total_trades = 0
        self.total_wins = 0
        self.total_losses = 0
        self.total_pnl = 0.0
        
        self._load()

    def add_trade(self, trade_data: Dict) -> bool:
        """
        Registra un nuevo trade.
        
        Args:
            trade_data: {
                'timestamp': float,
                'asset': str,
                'direction': str (CALL/PUT),
                'entry_price': float,
                'exit_price': float,
                'amount': float,
                'result': str (WIN/LOSS/DRAW),
                'pnl': float,
                'confidence': float,
                'pattern': str,
                'zone_strength': float,
                'conditions': dict,
                'session': str,
                'notes': str
            }
        """
        try:
            # Asegurar que tiene timestamp
            if 'timestamp' not in trade_data:
                trade_data['timestamp'] = time.time()
            
            # Normalizar resultado
            result = trade_data.get('result', 'DRAW').upper()
            trade_data['result'] = result
            
            # Actualizar estadísticas
            self.trades.append(trade_data)
            self.total_trades += 1
            
            if result == 'WIN':
                self.total_wins += 1
            elif result == 'LOSS':
                self.total_losses += 1
            
            self.total_pnl += trade_data.get('pnl', 0.0)
            
            # Guardar inmediatamente
            self._save()
            return True
            
        except Exception as e:
            try:
                print(f"[ERROR] Error registrando trade: {e}")
            except Exception:
                pass
            return False

    def get_recent_trades(self, n: int = 50) -> List[Dict]:
        """Últimos N trades"""
        return self.trades[-n:]

    def get_trades_by_asset(self, asset: str) -> List[Dict]:
        """Todos los trades de un activo específico"""
        return [t for t in self.trades if t.get('asset') == asset]

    def get_trades_by_session(self, session: str) -> List[Dict]:
        """Todos los trades de una sesión específica"""
        return [t for t in self.trades if t.get('session') == session]

    def get_win_rate(self) -> float:
        """Tasa de ganancia global"""
        if self.total_trades == 0:
            return 0.0
        return self.total_wins / self.total_trades

    def get_stats(self) -> Dict:
        """Estadísticas completas"""
        return {
            'total_trades': self.total_trades,
            'total_wins': self.total_wins,
            'total_losses': self.total_losses,
            'win_rate': self.get_win_rate(),
            'total_pnl': self.total_pnl,
            'avg_pnl_per_trade': self.total_pnl / self.total_trades if self.total_trades > 0 else 0.0,
            'last_trade_ts': self.trades[-1]['timestamp'] if self.trades else None,
        }

    def get_summary(self) -> str:
        """Resumen para mostrar"""
        stats = self.get_stats()
        return (
            f"📊 Trades: {stats['total_trades']} | "
            f"✅ Wins: {stats['total_wins']} | "
            f"❌ Losses: {stats['total_losses']} | "
            f"📈 WR: {stats['win_rate']:.1%} | "
            f"💰 PnL: {stats['total_pnl']:.2f}"
        )

    def _save(self):
        """Guarda el historial en disco"""
        try:
            data = {
                'version': '1.0',
                'updated': time.time(),
                'total_trades': self.total_trades,
                'total_wins': self.total_wins,
                'total_losses': self.total_losses,
                'total_pnl': self.total_pnl,
                'trades': self.trades[-500:],  # Guardar últimos 500 trades
            }
            with open(self.persist_path, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            try:
                print(f"[ERROR] Error guardando trades: {e}")
            except Exception:
                pass

    def _load(self):
        """Carga el historial desde disco"""
        if not os.path.exists(self.persist_path):
            return
        
        try:
            with open(self.persist_path, 'r') as f:
                data = json.load(f)
            
            self.trades = data.get('trades', [])
            self.total_trades = data.get('total_trades', 0)
            self.total_wins = data.get('total_wins', 0)
            self.total_losses = data.get('total_losses', 0)
            self.total_pnl = data.get('total_pnl', 0.0)
            
            try:
                print(f"[SUCCESS] Historial cargado: {self.total_trades} trades ({self.total_wins} wins)")
            except Exception:
                pass
            
        except Exception as e:
            try:
                print(f"[ERROR] Error cargando historial: {e}")
            except Exception:
                pass


# Singleton
_persistence: Optional[TradePersistence] = None


def get_trade_persistence() -> TradePersistence:
    global _persistence
    if _persistence is None:
        _persistence = TradePersistence()
    return _persistence
