"""
ðŸŽ¯ MENÃš INTERACTIVO DE IA
Sistema de menÃº para interactuar con el predictor de IA
"""
import os
import sys
import json
from pathlib import Path

# Agregar ruta
sys.path.insert(0, str(Path(__file__).parent))

from .local_ai_predictor import get_local_ai_predictor
from ai_trading_integration import get_ai_trading_integration


def clear_screen():
    """Limpia la pantalla"""
    os.system('cls' if os.name == 'nt' else 'clear')


def print_header(title: str):
    """Imprime encabezado"""
    print(f"\n{'='*80}")
    print(f"  {title}")
    print(f"{'='*80}\n")


def print_menu(options: dict):
    """Imprime menÃº de opciones"""
    for key, value in options.items():
        print(f"  [{key}] {value}")
    print()


def main_menu():
    """MenÃº principal"""
    
    while True:
        clear_screen()
        print_header("ðŸ¤– SISTEMA DE IA PARA TRADING")
        
        print("Selecciona una opciÃ³n:\n")
        options = {
            '1': 'Analizar trades histÃ³ricos',
            '2': 'PredicciÃ³n de movimiento',
            '3': 'Recomendaciones de trading',
            '4': 'Ver estadÃ­sticas por activo',
            '5': 'Ver estadÃ­sticas por patrÃ³n',
            '6': 'Generar reporte completo',
            '7': 'Salir'
        }
        print_menu(options)
        
        choice = input("OpciÃ³n: ").strip()
        
        if choice == '1':
            analyze_trades()
        elif choice == '2':
            predict_movement()
        elif choice == '3':
            show_recommendations()
        elif choice == '4':
            show_asset_stats()
        elif choice == '5':
            show_pattern_stats()
        elif choice == '6':
            show_full_report()
        elif choice == '7':
            print("\n[OK] Saliendo...")
            break
        else:
            print("\n[ERROR] OpciÃ³n no vÃ¡lida")
            input("Presiona Enter para continuar...")


def analyze_trades():
    """Analiza trades histÃ³ricos"""
    
    clear_screen()
    print_header("ðŸ“Š ANÃLISIS DE TRADES HISTÃ“RICOS")
    
    predictor = get_local_ai_predictor()
    analysis = predictor.analyze_trades()
    
    print(f"Total de trades: {analysis['total_trades']}")
    print(f"Ganancias: {analysis['wins']} ({analysis['win_rate']:.1%})")
    print(f"PÃ©rdidas: {analysis['losses']} ({1-analysis['win_rate']:.1%})")
    print(f"PnL Total: {analysis['pnl_total']:+.2f}")
    print(f"PnL Promedio: {analysis['pnl_avg']:+.2f}\n")
    
    print("ðŸ† MEJORES ACTIVOS:")
    for asset_info in analysis.get('best_assets', []):
        print(f"  â€¢ {asset_info['asset']}: WR {asset_info['wr']:.1%}, PnL {asset_info['pnl']:+.2f}, Trades {asset_info['trades']}")
    
    print("\nâš ï¸  PEORES ACTIVOS:")
    for asset_info in analysis.get('worst_assets', []):
        print(f"  â€¢ {asset_info['asset']}: WR {asset_info['wr']:.1%}, PnL {asset_info['pnl']:+.2f}, Trades {asset_info['trades']}")
    
    print("\nðŸŽ¯ RECOMENDACIONES:")
    for rec in analysis.get('recommendations', []):
        print(f"  â€¢ {rec}")
    
    input("\nPresiona Enter para continuar...")


def predict_movement():
    """PredicciÃ³n de movimiento"""
    
    clear_screen()
    print_header("ðŸ”® PREDICCIÃ“N DE MOVIMIENTO")
    
    print("Ingresa los datos del mercado actual:\n")
    
    asset = input("Activo (ej: EURJPY-OTC): ").strip().upper()
    if not asset:
        asset = "EURJPY-OTC"
    
    try:
        price = float(input("Precio actual: ") or "0")
    except:
        price = 0
    
    try:
        rsi = float(input("RSI (0-100): ") or "50")
    except:
        rsi = 50
    
    trend = input("Tendencia (UP/DOWN/NEUTRAL): ").strip().upper()
    if trend not in ['UP', 'DOWN', 'NEUTRAL']:
        trend = 'NEUTRAL'
    
    pattern = input("PatrÃ³n (ej: pin_bar_bullish, none): ").strip().lower()
    if not pattern:
        pattern = 'none'
    
    nearby_zone = input("Zona cercana (opcional): ").strip()
    if not nearby_zone:
        nearby_zone = None
    
    # Realizar predicciÃ³n
    predictor = get_local_ai_predictor()
    market_context = {
        'asset': asset,
        'price': price,
        'rsi': rsi,
        'trend': trend,
        'pattern': pattern,
        'nearby_zone': nearby_zone
    }
    
    prediction = predictor.predict_next_move(market_context)
    
    print(f"\n{'='*80}")
    print(f"ðŸ“Š PREDICCIÃ“N PARA {asset}")
    print(f"{'='*80}\n")
    
    print(f"DirecciÃ³n: {prediction['direction']}")
    print(f"Confianza: {prediction['confidence']:.0f}%")
    print(f"AcciÃ³n: {prediction['action']}")
    print(f"\nFactores considerados:")
    for factor, value in prediction['factors'].items():
        if isinstance(value, float):
            print(f"  â€¢ {factor}: {value:.2f}")
        else:
            print(f"  â€¢ {factor}: {value}")
    
    print(f"\nRazonamiento:")
    for reason in prediction['reasoning']:
        print(f"  â€¢ {reason}")
    
    input("\nPresiona Enter para continuar...")


def show_recommendations():
    """Muestra recomendaciones"""
    
    clear_screen()
    print_header("ðŸŽ¯ RECOMENDACIONES DE TRADING")
    
    integration = get_ai_trading_integration()
    recommendations = integration.analyze_and_recommend()
    
    print(f"AnÃ¡lisis realizado: {recommendations['timestamp']}\n")
    
    print("ACCIONES RECOMENDADAS:")
    for action in recommendations['actions']:
        if action['type'] == 'INCREASE_VOLUME':
            print(f"  âœ“ AUMENTAR volumen en {action['asset']}")
            print(f"    Multiplicador: {action['multiplier']}x")
            print(f"    RazÃ³n: {action['reason']}\n")
        elif action['type'] == 'PAUSE_ASSET':
            print(f"  âœ— PAUSAR {action['asset']}")
            print(f"    RazÃ³n: {action['reason']}\n")
    
    improvement = recommendations['expected_improvement']
    print(f"MEJORA ESPERADA:")
    print(f"  â€¢ WR Actual: {improvement['current_wr']:.1%}")
    print(f"  â€¢ WR Objetivo: {improvement['target_wr']:.1%}")
    print(f"  â€¢ Mejora: +{improvement['improvement_pct']:.1f}%")
    
    input("\nPresiona Enter para continuar...")


def show_asset_stats():
    """Muestra estadÃ­sticas por activo"""
    
    clear_screen()
    print_header("ðŸ“ˆ ESTADÃSTICAS POR ACTIVO")
    
    predictor = get_local_ai_predictor()
    
    print("Activos disponibles:\n")
    for i, (asset, stats) in enumerate(predictor.asset_stats.items(), 1):
        wr = stats.get('win_rate', 0)
        pnl = stats.get('pnl_total', 0)
        trades = stats.get('total', 0)
        print(f"  [{i}] {asset}: WR {wr:.1%}, PnL {pnl:+.2f}, Trades {trades}")
    
    print()
    choice = input("Selecciona activo (nÃºmero o nombre): ").strip()
    
    # Buscar activo
    asset = None
    if choice.isdigit():
        idx = int(choice) - 1
        assets = list(predictor.asset_stats.keys())
        if 0 <= idx < len(assets):
            asset = assets[idx]
    else:
        asset = choice.upper()
    
    if asset and asset in predictor.asset_stats:
        stats = predictor.asset_stats[asset]
        
        clear_screen()
        print_header(f"ðŸ“Š ESTADÃSTICAS DE {asset}")
        
        print(f"Total de trades: {stats['total']}")
        print(f"Ganancias: {stats['wins']} ({stats['win_rate']:.1%})")
        print(f"PÃ©rdidas: {stats['losses']} ({1-stats['win_rate']:.1%})")
        print(f"PnL Total: {stats['pnl_total']:+.2f}")
        print(f"PnL Promedio: {stats['pnl_avg']:+.2f}")
        print(f"RSI Promedio: {stats['rsi_avg']:.1f}")
    else:
        print(f"\n[ERROR] Activo no encontrado")
    
    input("\nPresiona Enter para continuar...")


def show_pattern_stats():
    """Muestra estadÃ­sticas por patrÃ³n"""
    
    clear_screen()
    print_header("ðŸŽ¨ ESTADÃSTICAS POR PATRÃ“N")
    
    predictor = get_local_ai_predictor()
    
    print("Patrones disponibles:\n")
    for i, (pattern, stats) in enumerate(predictor.pattern_stats.items(), 1):
        wr = stats.get('win_rate', 0)
        trades = stats.get('total', 0)
        conf = stats.get('confidence', 0)
        print(f"  [{i}] {pattern}: WR {wr:.1%}, Trades {trades}, Confianza {conf:.0f}%")
    
    print()
    choice = input("Selecciona patrÃ³n (nÃºmero o nombre): ").strip()
    
    # Buscar patrÃ³n
    pattern = None
    if choice.isdigit():
        idx = int(choice) - 1
        patterns = list(predictor.pattern_stats.keys())
        if 0 <= idx < len(patterns):
            pattern = patterns[idx]
    else:
        pattern = choice.lower()
    
    if pattern and pattern in predictor.pattern_stats:
        stats = predictor.pattern_stats[pattern]
        
        clear_screen()
        print_header(f"ðŸŽ¨ ESTADÃSTICAS DE {pattern}")
        
        print(f"Total de trades: {stats['total']}")
        print(f"Ganancias: {stats['wins']} ({stats['win_rate']:.1%})")
        print(f"PÃ©rdidas: {stats['losses']} ({1-stats['win_rate']:.1%})")
        print(f"PnL Total: {stats['pnl_total']:+.2f}")
        print(f"Confianza: {stats['confidence']:.0f}%")
    else:
        print(f"\n[ERROR] PatrÃ³n no encontrado")
    
    input("\nPresiona Enter para continuar...")


def show_full_report():
    """Muestra reporte completo"""
    
    clear_screen()
    print_header("ðŸ“‹ REPORTE COMPLETO")
    
    integration = get_ai_trading_integration()
    report = integration.generate_report()
    
    print(report)
    
    input("Presiona Enter para continuar...")


if __name__ == "__main__":
    try:
        main_menu()
    except KeyboardInterrupt:
        print("\n\n[!] Programa interrumpido por el usuario")
    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()

