"""
TRADE CONTEXT ANALYZER v1.0
═══════════════════════════════════════════════════════════════════════════════

Captura el CONTEXTO COMPLETO de cada operación:
- Variables técnicas (zona, RSI, patrones, etc.)
- Variables macro (tendencia H1, consolidación, etc.)
- Resultado (WIN/LOSS)
- Lecciones aprendidas

Uso: Cada trade que se ejecuta se analiza y guarda en JSON.
Luego se pueden extraer patrones: "¿Cuándo gano?" "¿Cuándo pierdo?"
"""

import json
import os
from datetime import datetime
from typing import Dict, Optional, Any
import pandas as pd


class TradeContextAnalyzer:
    
    def __init__(self, storage_path: str = "data/trades_analysis.json"):
        self.storage_path = storage_path
        os.makedirs(os.path.dirname(storage_path), exist_ok=True)
        self.trades = self._load_trades()
    
    def _load_trades(self) -> list:
        """Carga historial de trades del JSON."""
        if os.path.exists(self.storage_path):
            try:
                with open(self.storage_path, 'r') as f:
                    return json.load(f)
            except:
                return []
        return []
    
    def _save_trades(self):
        """Guarda el historial."""
        with open(self.storage_path, 'w') as f:
            json.dump(self.trades, f, indent=2)
    
    def record_trade(self, 
                     pair: str,
                     direction: str,  # "CALL" o "PUT"
                     entry_price: float,
                     entry_time: str,
                     expiration: int,  # segundos
                     zone_info: Dict[str, Any],
                     market_context: Dict[str, Any],
                     technical_conditions: Dict[str, bool],
                     ai_confidence: float,
                     pattern: str,  # "breakout", "reversal", "3phase", etc.
                     complexity: int,  # 0-100
                     ) -> str:
        """
        Registra un TRADE ANTES de ejecutarlo.
        Retorna trade_id para actualizar después con resultado.
        """
        trade_id = f"{pair}_{entry_time.replace(':', '').replace('-', '')}_{int(entry_price*10000)}"
        
        trade_record = {
            "trade_id": trade_id,
            "timestamp": datetime.now().isoformat(),
            "pair": pair,
            "direction": direction,
            "entry_price": entry_price,
            "entry_time": entry_time,
            "expiration_seconds": expiration,
            
            # CONTEXTO DE ZONA
            "zone": {
                "support_level": zone_info.get("support_level", 0.0),
                "resistance_level": zone_info.get("resistance_level", 0.0),
                "strength": zone_info.get("strength", 0.0),
                "hold_rate": zone_info.get("hold_rate", 0.0),
                "touches": zone_info.get("touches", 0),
                "distance_to_zone": zone_info.get("distance_to_zone", 0.0),
                "is_strong": zone_info.get("strength", 0.0) >= 0.7,
            },
            
            # CONTEXTO MACRO
            "market_context": {
                "macro_trend": market_context.get("macro_trend", "neutral"),
                "h1_trend": market_context.get("h1_trend", "neutral"),
                "m15_trend": market_context.get("m15_trend", "neutral"),
                "consolidation_level": market_context.get("consolidation_level", 0.5),
                "is_consolidating": market_context.get("consolidation_level", 0.5) > 0.7,
                "rsi_m1": market_context.get("rsi_m1", 50),
                "rsi_m5": market_context.get("rsi_m5", 50),
                "atr_m5": market_context.get("atr_m5", 0.0),
                "volatility": "high" if market_context.get("atr_m5", 0.0) > 0.5 else "normal" if market_context.get("atr_m5", 0.0) > 0.2 else "low",
            },
            
            # CONDICIONES TÉCNICAS QUE DISPARARON LA ENTRADA
            "technical_conditions": technical_conditions,
            "conditions_count": sum(1 for v in technical_conditions.values() if v),
            
            # SEÑAL DE IA
            "ai_confidence": ai_confidence,
            "ai_signal": "strong" if ai_confidence > 0.75 else "medium" if ai_confidence > 0.50 else "weak",
            
            # PATRÓN Y COMPLEJIDAD
            "pattern": pattern,
            "complexity": complexity,
            "is_breakout": pattern == "breakout",
            "is_3phase": pattern == "3phase",
            "is_reversal": pattern == "reversal",
            
            # TRADE RESULT (se actualiza después)
            "result": None,  # "WIN", "LOSS"
            "exit_price": None,
            "pnl": None,
            "pnl_percent": None,
            "lessons": [],  # Se llenan después
        }
        
        self.trades.append(trade_record)
        self._save_trades()
        return trade_id
    
    def update_trade_result(self,
                           trade_id: str,
                           result: str,  # "WIN" o "LOSS"
                           exit_price: float,
                           pnl: float,
                           pnl_percent: float,
                           lessons: list = None):
        """
        Actualiza un trade con su resultado.
        Lessons: observaciones sobre por qué ganó/perdió
        """
        for trade in self.trades:
            if trade["trade_id"] == trade_id:
                trade["result"] = result
                trade["exit_price"] = exit_price
                trade["pnl"] = pnl
                trade["pnl_percent"] = pnl_percent
                trade["lessons"] = lessons or []
                self._save_trades()
                return True
        return False
    
    # ─────────────────────────────────────────────────────────────────────────────
    # ANÁLISIS: Buscar patrones ganadores
    # ─────────────────────────────────────────────────────────────────────────────
    
    def analyze_patterns(self) -> Dict:
        """
        Analiza todos los trades para encontrar PATRONES GANADORES.
        Retorna: {
            "total_trades": N,
            "win_rate": X%,
            "winning_patterns": {...},
            "losing_patterns": {...},
            "best_conditions": {...},
            "worst_conditions": {...},
        }
        """
        if not self.trades:
            return {"message": "No trades yet"}
        
        # Filtrar solo trades completados
        completed = [t for t in self.trades if t["result"] is not None]
        if not completed:
            return {"message": "No completed trades yet"}
        
        wins = [t for t in completed if t["result"] == "WIN"]
        losses = [t for t in completed if t["result"] == "LOSS"]
        
        # ─── Análisis por PATRÓN ───
        pattern_stats = {}
        for trade in completed:
            pattern = trade["pattern"]
            if pattern not in pattern_stats:
                pattern_stats[pattern] = {"wins": 0, "losses": 0, "total": 0, "pnl": 0.0}
            
            pattern_stats[pattern]["total"] += 1
            pattern_stats[pattern]["pnl"] += trade.get("pnl", 0)
            if trade["result"] == "WIN":
                pattern_stats[pattern]["wins"] += 1
            else:
                pattern_stats[pattern]["losses"] += 1
        
        # ─── Análisis por MACRO TREND ───
        trend_stats = {}
        for trade in completed:
            macro_trend = trade["market_context"]["macro_trend"]
            if macro_trend not in trend_stats:
                trend_stats[macro_trend] = {"wins": 0, "losses": 0, "total": 0, "pnl": 0.0}
            
            trend_stats[macro_trend]["total"] += 1
            trend_stats[macro_trend]["pnl"] += trade.get("pnl", 0)
            if trade["result"] == "WIN":
                trend_stats[macro_trend]["wins"] += 1
            else:
                trend_stats[macro_trend]["losses"] += 1
        
        # ─── Análisis por ZONE STRENGTH ───
        zone_strength_stats = {
            "strong": {"wins": 0, "losses": 0, "total": 0, "pnl": 0.0},
            "weak": {"wins": 0, "losses": 0, "total": 0, "pnl": 0.0},
        }
        for trade in completed:
            zone_type = "strong" if trade["zone"]["is_strong"] else "weak"
            zone_strength_stats[zone_type]["total"] += 1
            zone_strength_stats[zone_type]["pnl"] += trade.get("pnl", 0)
            if trade["result"] == "WIN":
                zone_strength_stats[zone_type]["wins"] += 1
            else:
                zone_strength_stats[zone_type]["losses"] += 1
        
        # ─── Análisis por CONSOLIDATION ───
        consolidation_stats = {
            "consolidated": {"wins": 0, "losses": 0, "total": 0, "pnl": 0.0},
            "trending": {"wins": 0, "losses": 0, "total": 0, "pnl": 0.0},
        }
        for trade in completed:
            cons_type = "consolidated" if trade["market_context"]["is_consolidating"] else "trending"
            consolidation_stats[cons_type]["total"] += 1
            consolidation_stats[cons_type]["pnl"] += trade.get("pnl", 0)
            if trade["result"] == "WIN":
                consolidation_stats[cons_type]["wins"] += 1
            else:
                consolidation_stats[cons_type]["losses"] += 1
        
        # ─── Análisis por AI CONFIDENCE ───
        confidence_stats = {
            "high": {"wins": 0, "losses": 0, "total": 0, "pnl": 0.0},    # >= 75%
            "medium": {"wins": 0, "losses": 0, "total": 0, "pnl": 0.0},  # 50-75%
            "low": {"wins": 0, "losses": 0, "total": 0, "pnl": 0.0},     # < 50%
        }
        for trade in completed:
            conf = trade["ai_confidence"]
            if conf >= 0.75:
                conf_level = "high"
            elif conf >= 0.50:
                conf_level = "medium"
            else:
                conf_level = "low"
            
            confidence_stats[conf_level]["total"] += 1
            confidence_stats[conf_level]["pnl"] += trade.get("pnl", 0)
            if trade["result"] == "WIN":
                confidence_stats[conf_level]["wins"] += 1
            else:
                confidence_stats[conf_level]["losses"] += 1
        
        # ─── Síntesis ───
        return {
            "summary": {
                "total_trades": len(completed),
                "total_wins": len(wins),
                "total_losses": len(losses),
                "win_rate": round(len(wins) / len(completed) * 100, 2) if completed else 0,
                "total_pnl": round(sum(t.get("pnl", 0) for t in completed), 2),
                "avg_win": round(sum(t.get("pnl", 0) for t in wins) / len(wins), 2) if wins else 0,
                "avg_loss": round(sum(t.get("pnl", 0) for t in losses) / len(losses), 2) if losses else 0,
            },
            "by_pattern": pattern_stats,
            "by_macro_trend": trend_stats,
            "by_zone_strength": zone_strength_stats,
            "by_consolidation": consolidation_stats,
            "by_ai_confidence": confidence_stats,
        }
    
    def get_best_setup(self) -> Dict:
        """Retorna el setup que más ha ganado."""
        analysis = self.analyze_patterns()
        
        # Encontrar mejor patrón
        best_pattern = max(
            analysis.get("by_pattern", {}).items(),
            key=lambda x: x[1]["wins"] - x[1]["losses"] if x[1]["total"] > 0 else 0,
            default=("unknown", {})
        )
        
        # Encontrar mejor tendencia macro
        best_trend = max(
            analysis.get("by_macro_trend", {}).items(),
            key=lambda x: x[1]["wins"] - x[1]["losses"] if x[1]["total"] > 0 else 0,
            default=("unknown", {})
        )
        
        return {
            "best_pattern": {
                "name": best_pattern[0],
                "stats": best_pattern[1],
            },
            "best_macro_trend": {
                "name": best_trend[0],
                "stats": best_trend[1],
            },
            "recommendation": f"Enfocarse en {best_pattern[0]} trades en tendencia {best_trend[0]}",
        }
    
    def get_worst_setup(self) -> Dict:
        """Retorna el setup que más ha perdido."""
        analysis = self.analyze_patterns()
        
        # Encontrar peor patrón
        worst_pattern = min(
            analysis.get("by_pattern", {}).items(),
            key=lambda x: x[1]["wins"] - x[1]["losses"] if x[1]["total"] > 0 else float('inf'),
            default=("unknown", {})
        )
        
        # Encontrar peor tendencia macro
        worst_trend = min(
            analysis.get("by_macro_trend", {}).items(),
            key=lambda x: x[1]["wins"] - x[1]["losses"] if x[1]["total"] > 0 else float('inf'),
            default=("unknown", {})
        )
        
        return {
            "worst_pattern": {
                "name": worst_pattern[0],
                "stats": worst_pattern[1],
            },
            "worst_macro_trend": {
                "name": worst_trend[0],
                "stats": worst_trend[1],
            },
            "warning": f"⚠️ EVITAR: {worst_pattern[0]} trades en tendencia {worst_trend[0]}",
        }
    
    def export_analysis_report(self, filename: str = "data/trade_analysis_report.md") -> str:
        """Exporta análisis en formato Markdown."""
        analysis = self.analyze_patterns()
        best_setup = self.get_best_setup()
        worst_setup = self.get_worst_setup()
        
        report = f"""# 📊 TRADE ANALYSIS REPORT
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## Summary
- Total Trades: {analysis['summary']['total_trades']}
- Wins: {analysis['summary']['total_wins']}
- Losses: {analysis['summary']['total_losses']}
- Win Rate: {analysis['summary']['win_rate']}%
- Total PnL: ${analysis['summary']['total_pnl']}
- Avg Win: ${analysis['summary']['avg_win']}
- Avg Loss: ${analysis['summary']['avg_loss']}

## Best Setup
🎯 Pattern: {best_setup['best_pattern']['name']}
   - Wins: {best_setup['best_pattern']['stats'].get('wins', 0)}
   - Losses: {best_setup['best_pattern']['stats'].get('losses', 0)}

📊 Macro Trend: {best_setup['best_macro_trend']['name']}
   - Wins: {best_setup['best_macro_trend']['stats'].get('wins', 0)}
   - Losses: {best_setup['best_macro_trend']['stats'].get('losses', 0)}

## Worst Setup
⚠️ Pattern: {worst_setup['worst_pattern']['name']}
   - Wins: {worst_setup['worst_pattern']['stats'].get('wins', 0)}
   - Losses: {worst_setup['worst_pattern']['stats'].get('losses', 0)}

📉 Macro Trend: {worst_setup['worst_macro_trend']['name']}
   - Wins: {worst_setup['worst_macro_trend']['stats'].get('wins', 0)}
   - Losses: {worst_setup['worst_macro_trend']['stats'].get('losses', 0)}

## By Pattern Analysis
"""
        for pattern, stats in analysis.get('by_pattern', {}).items():
            wr = (stats['wins'] / stats['total'] * 100) if stats['total'] > 0 else 0
            report += f"- **{pattern}**: {stats['total']} trades, {wr:.1f}% WR, ${stats['pnl']:.2f} PnL\n"
        
        report += f"\n## By Macro Trend\n"
        for trend, stats in analysis.get('by_macro_trend', {}).items():
            wr = (stats['wins'] / stats['total'] * 100) if stats['total'] > 0 else 0
            report += f"- **{trend}**: {stats['total']} trades, {wr:.1f}% WR, ${stats['pnl']:.2f} PnL\n"
        
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        with open(filename, 'w') as f:
            f.write(report)
        
        return report
