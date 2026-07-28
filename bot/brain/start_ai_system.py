#!/usr/bin/env python3
"""
🚀 SCRIPT DE INICIO - SISTEMA DE TRADING CON IA
Inicia el sistema completo con GitHub Copilot
"""
import sys
import os
import json
import time
from pathlib import Path

# Agregar ruta
sys.path.insert(0, str(Path(__file__).parent))

from ai_trading_system import get_ai_trading_system
from github_copilot_auth import get_github_copilot_auth


def print_banner():
    """Muestra banner de inicio"""
    banner = """
╔════════════════════════════════════════════════════════════════════════════════╗
║                                                                                ║
║                  🚀 SISTEMA DE TRADING CON IA - GITHUB COPILOT                ║
║                                                                                ║
║                    Análisis Profundo • Predicción • Optimización               ║
║                                                                                ║
╚════════════════════════════════════════════════════════════════════════════════╝
"""
    print(banner)


def print_menu():
    """Muestra menú principal"""
    menu = """
╔════════════════════════════════════════════════════════════════════════════════╗
║                            MENU PRINCIPAL                                      ║
╚════════════════════════════════════════════════════════════════════════════════╝

1. [AUTENTICACIÓN] Autenticar con GitHub Copilot
2. [ANÁLISIS] Ejecutar análisis completo
3. [PREDICCIÓN] Predecir próximo movimiento
4. [ESTRATEGIA] Generar estrategia personalizada
5. [OPTIMIZACIÓN] Optimizar parámetros
6. [ESTADO] Ver estado del sistema
7. [REPORTE] Generar reporte completo
8. [SALIR] Salir del programa

Selecciona una opción (1-8):
"""
    return menu


def main():
    """Función principal"""
    
    print_banner()
    
    # Inicializar sistema
    print("\n[*] Inicializando sistema...")
    system = get_ai_trading_system()
    
    # Menú interactivo
    while True:
        print(print_menu(), end='')
        
        try:
            choice = input().strip()
            
            if choice == '1':
                # Autenticación
                print("\n[*] Iniciando autenticación con GitHub Copilot...")
                auth = get_github_copilot_auth()
                token = auth.authenticate()
                
                if token:
                    print(f"\n[OK] Autenticación exitosa")
                    user_info = auth.get_user_info()
                else:
                    print(f"\n[ERROR] Autenticación fallida")
            
            elif choice == '2':
                # Análisis completo
                print("\n[*] Ejecutando análisis completo...")
                system.initialize()
                print(f"\n[OK] Análisis completado")
            
            elif choice == '3':
                # Predicción
                print("\n[*] Prediciendo próximo movimiento...")
                
                # Contexto de ejemplo
                context = {
                    'asset': 'EURJPY-OTC',
                    'price': 186.47,
                    'rsi': 55,
                    'trend': 'NEUTRAL',
                    'session': 'EUROPE',
                    'nearby_zone': 186.47,
                    'pattern': 'pin_bar_bullish'
                }
                
                prediction = system.analyze_current_market(context)
                print(f"\n[OK] Predicción completada")
                print(json.dumps(prediction, indent=2, default=str))
            
            elif choice == '4':
                # Estrategia
                print("\n[*] Generando estrategia personalizada...")
                
                conditions = {
                    'volatility': 'media',
                    'trend': 'neutral',
                    'session': 'EUROPE',
                    'assets': ['EURJPY-OTC', 'GBPUSD-OTC', 'EURUSD-OTC'],
                    'current_wr': 0.524
                }
                
                strategy = system.ai_brain.generate_strategy(conditions)
                print(f"\n[OK] Estrategia generada")
                print(json.dumps(strategy, indent=2, default=str))
            
            elif choice == '5':
                # Optimización
                print("\n[*] Optimizando parámetros...")
                
                performance = {
                    'wr': 0.524,
                    'pnl': 160.15,
                    'sharpe': 1.2
                }
                
                optimization = system.optimize_system(performance)
                print(f"\n[OK] Optimización completada")
                print(json.dumps(optimization, indent=2, default=str))
            
            elif choice == '6':
                # Estado
                print("\n[*] Obteniendo estado del sistema...")
                status = system.get_status()
                print(f"\n[OK] Estado actual:")
                print(json.dumps(status, indent=2, default=str))
            
            elif choice == '7':
                # Reporte
                print("\n[*] Generando reporte completo...")
                report = system.generate_full_report()
                print(report)
            
            elif choice == '8':
                # Salir
                print("\n[*] Saliendo...")
                print("[OK] Hasta luego!")
                break
            
            else:
                print("\n[ERROR] Opción inválida")
            
            # Pausa antes de volver al menú
            input("\nPresiona Enter para continuar...")
            print("\n" * 2)
        
        except KeyboardInterrupt:
            print("\n\n[*] Programa interrumpido por el usuario")
            break
        except Exception as e:
            print(f"\n[ERROR] {e}")
            input("\nPresiona Enter para continuar...")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n[ERROR] Error fatal: {e}")
        sys.exit(1)
