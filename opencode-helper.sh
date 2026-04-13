#!/bin/bash
# Script helper para usar OpenCode localmente o en Docker

set -e

# Colores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Funciones
print_status() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

# Verificar si Docker está instalado
check_docker() {
    if ! command -v docker &> /dev/null; then
        print_error "Docker no está instalado"
        echo "Instala Docker: https://docs.docker.com/get-docker/"
        exit 1
    fi
    print_success "Docker disponible"
}

# Verificar si docker-compose está instalado
check_docker_compose() {
    if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
        print_error "Docker Compose no está instalado"
        exit 1
    fi
    print_success "Docker Compose disponible"
}

# Construir imagen
build_image() {
    print_status "Construyendo imagen Docker con OpenCode..."
    docker build -f Dockerfile.opencode -t exnova-trading-opencode:latest .
    print_success "Imagen construida: exnova-trading-opencode:latest"
}

# Ejecutar OpenCode en modo interactivo
run_opencode() {
    print_status "Iniciando OpenCode en contenedor..."
    print_warning "Asegúrate de tener las variables de entorno configuradas"

    # Verificar archivo .env
    if [ -f .env ]; then
        print_success "Archivo .env encontrado"
        ENV_FILE="--env-file .env"
    else
        print_warning "No se encontró .env - usando variables de entorno del sistema"
        ENV_FILE=""
    fi

    docker run -it --rm \
        $ENV_FILE \
        -v "$(pwd):/app" \
        -v "/app/node_modules" \
        exnova-trading-opencode:latest \
        opencode "$@"
}

# Ejecutar shell interactivo
run_shell() {
    print_status "Abriendo shell en contenedor..."

    if [ -f .env ]; then
        ENV_FILE="--env-file .env"
    else
        ENV_FILE=""
    fi

    docker run -it --rm \
        $ENV_FILE \
        -v "$(pwd):/app" \
        -v "/app/node_modules" \
        exnova-trading-opencode:latest \
        /bin/bash
}

# Ejecutar el bot
run_bot() {
    print_status "Iniciando Bot de Trading..."

    if [ -f .env ]; then
        ENV_FILE="--env-file .env"
    else
        ENV_FILE=""
    fi

    docker run -it --rm \
        $ENV_FILE \
        -v "$(pwd):/app" \
        -v "/app/node_modules" \
        exnova-trading-opencode:latest \
        python bot_con_ia.py
}

# Ejecutar con docker-compose
run_compose() {
    print_status "Iniciando con Docker Compose..."

    if [ -f .env ]; then
        print_success "Usando variables de .env"
    else
        print_warning "Crea un archivo .env con tus credenciales"
    fi

    docker-compose -f docker-compose.opencode.yml up "$@"
}

# Mostrar ayuda
show_help() {
    cat << EOF
🚀 OpenCode Helper Script

Uso: ./opencode-helper.sh [comando] [opciones]

Comandos:
  build           Construir la imagen Docker
  opencode        Ejecutar OpenCode en modo interactivo
  shell           Abrir shell bash en el contenedor
  bot             Ejecutar el bot de trading
  compose-up      Iniciar servicios con docker-compose
  compose-down    Detener servicios de docker-compose
  help            Mostrar esta ayuda

Ejemplos:
  ./opencode-helper.sh build
  ./opencode-helper.sh opencode
  ./opencode-helper.sh shell
  ./opencode-helper.sh bot
  ./opencode-helper.sh compose-up -d

Variables de entorno necesarias:
  EXNOVA_EMAIL        Email de Exnova
  EXNOVA_PASSWORD     Password de Exnova
  ANTHROPIC_API_KEY   API Key de Anthropic (opcional)
  OPENAI_API_KEY      API Key de OpenAI (opcional)
  GROQ_API_KEY        API Key de Groq (opcional)

EOF
}

# Main
case "${1:-help}" in
    build)
        check_docker
        build_image
        ;;
    opencode)
        check_docker
        shift
        run_opencode "$@"
        ;;
    shell)
        check_docker
        run_shell
        ;;
    bot)
        check_docker
        run_bot
        ;;
    compose-up)
        check_docker
        check_docker_compose
        shift
        run_compose "$@"
        ;;
    compose-down)
        check_docker_compose
        docker-compose -f docker-compose.opencode.yml down
        ;;
    help|--help|-h)
        show_help
        ;;
    *)
        print_error "Comando desconocido: $1"
        show_help
        exit 1
        ;;
esac
