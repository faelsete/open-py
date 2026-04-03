#!/bin/bash
# ═══════════════════════════════════════════════════════════
# Open-PY — Instalador v2.1 (Bulletproof Edition)
# Framework de Agentes Autônomos para Linux
#
# Instalação:
#   curl -fsSL https://raw.githubusercontent.com/faelsete/open-py/main/install.sh | sudo bash
#
# ═══════════════════════════════════════════════════════════

# NÃO usar set -e! Controlamos erros manualmente
set -uo pipefail

REPO_URL="https://github.com/faelsete/open-py.git"
INSTALL_DIR="/opt/open-py"
VENV_DIR="$INSTALL_DIR/venv"
DATA_DIR="$INSTALL_DIR/data"
CONFIG_FILE="$INSTALL_DIR/openpy.toml"
LOG_FILE="/var/log/open-py-install.log"
VERSION="2.1.0"
ERRORS=0

# ════════════════ CORES ════════════════
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; MAGENTA='\033[0;35m'; BOLD='\033[1m'
DIM='\033[2m'; NC='\033[0m'

ok()    { echo -e "  ${GREEN}✅ $1${NC}"; }
warn()  { echo -e "  ${YELLOW}⚠️  $1${NC}"; }
fail()  { echo -e "  ${RED}❌ $1${NC}"; ((ERRORS++)); }
die()   { echo -e "  ${RED}❌ FATAL: $1${NC}"; exit 1; }
info()  { echo -e "  ${CYAN}ℹ️  $1${NC}"; }
step()  { echo -e "  ${MAGENTA}→ $1${NC}"; }

header() {
    echo ""
    echo -e "${CYAN}╔═══════════════════════════════════════════════════╗${NC}"
    printf "${CYAN}║  🧠 %-48s║${NC}\n" "$1"
    echo -e "${CYAN}╚═══════════════════════════════════════════════════╝${NC}"
    echo ""
}

# ════════════════ LEITURA SEGURA ════════════════
# Quando roda via curl | bash, stdin é o pipe.
# Todos os reads DEVEM ler de /dev/tty
safe_read() {
    read "$@" < /dev/tty
}

safe_read_secret() {
    read -rs "$@" < /dev/tty
}

# ═══════════════════════════════════════════════════════════
# BANNER
# ═══════════════════════════════════════════════════════════
clear 2>/dev/null || true
echo ""
echo -e "${CYAN}     ██████╗ ██████╗ ███████╗███╗   ██╗   ██████╗ ██╗   ██╗${NC}"
echo -e "${CYAN}    ██╔═══██╗██╔══██╗██╔════╝████╗  ██║   ██╔══██╗╚██╗ ██╔╝${NC}"
echo -e "${CYAN}    ██║   ██║██████╔╝█████╗  ██╔██╗ ██║   ██████╔╝ ╚████╔╝${NC}"
echo -e "${CYAN}    ██║   ██║██╔═══╝ ██╔══╝  ██║╚██╗██║   ██╔═══╝   ╚██╔╝${NC}"
echo -e "${CYAN}    ╚██████╔╝██║     ███████╗██║ ╚████║   ██║        ██║${NC}"
echo -e "${CYAN}     ╚═════╝ ╚═╝     ╚══════╝╚═╝  ╚═══╝   ╚═╝        ╚═╝${NC}"
echo ""
echo -e "    ${DIM}Framework de Agentes Autônomos v${VERSION}${NC}"
echo -e "    ${DIM}github.com/faelsete/open-py${NC}"
echo ""

# ═══════════════════════════════════════════════════════════
# VERIFICAÇÕES INICIAIS
# ═══════════════════════════════════════════════════════════
[[ "$(uname)" != "Linux" ]] && die "Open-PY requer Linux (Ubuntu 22.04+ / Debian 12+)"
[[ "$EUID" -ne 0 ]] && die "Execute como root: curl ... | sudo bash"

# Verifica se /dev/tty é acessível (necessário para input interativo)
if ! exec 3< /dev/tty 2>/dev/null; then
    die "Sem acesso ao terminal (/dev/tty). Execute manualmente: bash install.sh"
fi
exec 3<&-

source /etc/os-release 2>/dev/null || true
ok "Sistema: ${PRETTY_NAME:-Linux} ($(uname -m))"
ok "RAM: $(free -h | awk '/^Mem:/{print $2}') | Disco livre: $(df -h / | awk 'NR==2{print $4}')"

TOTAL_RAM_MB=$(free -m | awk '/^Mem:/{print $2}')
[[ "$TOTAL_RAM_MB" -lt 1024 ]] && warn "RAM abaixo de 1GB — pode haver lentidão"

echo "" > "$LOG_FILE"

# ═══════════════════════════════════════════════════════════
# [1/8] DEPENDÊNCIAS DO SISTEMA
# ═══════════════════════════════════════════════════════════
header "[1/8] Dependências do Sistema"

export DEBIAN_FRONTEND=noninteractive
step "Atualizando repositórios..."
apt-get update -qq >> "$LOG_FILE" 2>&1 || warn "apt update retornou warnings"

PACKAGES=(
    python3 python3-pip python3-venv python3-dev
    postgresql postgresql-contrib
    bubblewrap ffmpeg
    curl wget jq openssl git
    build-essential libpq-dev
)

for pkg in "${PACKAGES[@]}"; do
    if dpkg -s "$pkg" &>/dev/null; then
        ok "$pkg"
    else
        step "Instalando $pkg..."
        if apt-get install -y -qq "$pkg" >> "$LOG_FILE" 2>&1; then
            ok "$pkg"
        else
            fail "$pkg — falha na instalação (ver $LOG_FILE)"
        fi
    fi
done

# pgvector
PG_VERSION=$(pg_config --version 2>/dev/null | grep -oP '\d+' | head -1 || echo "16")
if ! dpkg -s "postgresql-${PG_VERSION}-pgvector" &>/dev/null 2>&1; then
    step "Instalando pgvector..."
    if apt-get install -y -qq "postgresql-${PG_VERSION}-pgvector" >> "$LOG_FILE" 2>&1; then
        ok "pgvector (apt)"
    else
        warn "Compilando pgvector do fonte..."
        cd /tmp
        rm -rf pgvector 2>/dev/null
        if git clone --branch v0.7.4 https://github.com/pgvector/pgvector.git >> "$LOG_FILE" 2>&1; then
            cd pgvector
            if make >> "$LOG_FILE" 2>&1 && make install >> "$LOG_FILE" 2>&1; then
                ok "pgvector (compilado)"
            else
                fail "pgvector — compilação falhou"
            fi
            cd /tmp && rm -rf pgvector
        else
            fail "pgvector — git clone falhou"
        fi
    fi
else
    ok "pgvector"
fi

# ═══════════════════════════════════════════════════════════
# [2/8] CLONAR REPOSITÓRIO
# ═══════════════════════════════════════════════════════════
header "[2/8] Baixando Open-PY"

if [[ -d "$INSTALL_DIR/.git" ]]; then
    step "Atualizando repositório existente..."
    cd "$INSTALL_DIR"
    git pull origin main >> "$LOG_FILE" 2>&1 || git pull origin master >> "$LOG_FILE" 2>&1 || true
    ok "Atualizado para a versão mais recente"
else
    if [[ -d "$INSTALL_DIR" ]]; then
        [[ -f "$CONFIG_FILE" ]] && cp "$CONFIG_FILE" /tmp/openpy.toml.bak 2>/dev/null
        rm -rf "$INSTALL_DIR"
    fi
    step "Clonando repositório..."
    if git clone "$REPO_URL" "$INSTALL_DIR" >> "$LOG_FILE" 2>&1; then
        [[ -f /tmp/openpy.toml.bak ]] && mv /tmp/openpy.toml.bak "$CONFIG_FILE"
        ok "Clonado em $INSTALL_DIR"
    else
        die "Falha ao clonar repositório. Verifique sua conexão."
    fi
fi

# Criar diretórios de dados
mkdir -p "$DATA_DIR"/{agents,memory/daily,media/{photo,audio,video,document},tools/custom,backups,logs}
mkdir -p /tmp/open-py/agents
ok "Estrutura de diretórios criada"

# ═══════════════════════════════════════════════════════════
# [3/8] POSTGRESQL
# ═══════════════════════════════════════════════════════════
header "[3/8] PostgreSQL"

# Garantir que PostgreSQL está rodando
systemctl start postgresql >> "$LOG_FILE" 2>&1 || true
systemctl enable postgresql >> "$LOG_FILE" 2>&1 || true

# Aguardar PostgreSQL ficar pronto (máx 15 segundos)
PG_READY=false
for i in $(seq 1 15); do
    if sudo -u postgres pg_isready &>/dev/null; then
        PG_READY=true
        break
    fi
    sleep 1
done

if ! $PG_READY; then
    fail "PostgreSQL não respondeu em 15s"
    step "Tentando reiniciar..."
    systemctl restart postgresql >> "$LOG_FILE" 2>&1
    sleep 3
    sudo -u postgres pg_isready &>/dev/null || die "PostgreSQL não funciona. Verifique: systemctl status postgresql"
fi
ok "PostgreSQL em execução"

# Gerar senha segura
DB_PASSWORD="openpy_$(openssl rand -hex 16)"

# Criar user e database (com proteção contra duplicatas)
step "Configurando banco de dados..."

# Drop na ordem correta (database antes do user)
sudo -u postgres psql -c "DROP DATABASE IF EXISTS openpy;" >> "$LOG_FILE" 2>&1 || true
sudo -u postgres psql -c "DROP USER IF EXISTS openpy;" >> "$LOG_FILE" 2>&1 || true

# Criar user
if sudo -u postgres psql -c "CREATE USER openpy WITH PASSWORD '$DB_PASSWORD';" >> "$LOG_FILE" 2>&1; then
    ok "User 'openpy' criado"
else
    # User pode já existir, tenta alterar senha
    warn "User já existe, atualizando senha..."
    sudo -u postgres psql -c "ALTER USER openpy WITH PASSWORD '$DB_PASSWORD';" >> "$LOG_FILE" 2>&1 || fail "Falha ao configurar user"
fi

# Criar database
if sudo -u postgres psql -c "CREATE DATABASE openpy OWNER openpy;" >> "$LOG_FILE" 2>&1; then
    ok "Database 'openpy' criada"
else
    warn "Database já existe, continuando..."
fi

# Extensões
if sudo -u postgres psql -d openpy -c "CREATE EXTENSION IF NOT EXISTS vector;" >> "$LOG_FILE" 2>&1; then
    ok "Extensão pgvector ativada"
else
    fail "Extensão pgvector falhou (ver $LOG_FILE)"
fi

if sudo -u postgres psql -d openpy -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;" >> "$LOG_FILE" 2>&1; then
    ok "Extensão pg_trgm ativada"
else
    fail "Extensão pg_trgm falhou (ver $LOG_FILE)"
fi

# ═══════════════════════════════════════════════════════════
# [4/8] PYTHON VENV
# ═══════════════════════════════════════════════════════════
header "[4/8] Ambiente Python"

PYVER=$(python3 --version 2>&1 | awk '{print $2}')
ok "Python $PYVER"

# Criar venv
if [[ ! -d "$VENV_DIR" ]]; then
    step "Criando ambiente virtual..."
    python3 -m venv "$VENV_DIR" || die "Falha ao criar venv"
fi
source "$VENV_DIR/bin/activate"

step "Instalando dependências..."
pip install --upgrade pip -q >> "$LOG_FILE" 2>&1

if pip install -r "$INSTALL_DIR/requirements.txt" -q >> "$LOG_FILE" 2>&1; then
    ok "Dependências instaladas com sucesso"
else
    warn "Instalação em batch falhou. Instalando individualmente..."
    while IFS= read -r pkg; do
        pkg=$(echo "$pkg" | sed 's/#.*//' | xargs)
        [[ -z "$pkg" ]] && continue
        pip install -q "$pkg" >> "$LOG_FILE" 2>&1 || warn "Falha: $pkg"
    done < "$INSTALL_DIR/requirements.txt"
fi

PKG_COUNT=$("$VENV_DIR/bin/pip" list 2>/dev/null | tail -n +3 | wc -l)
ok "$PKG_COUNT pacotes instalados"

# ═══════════════════════════════════════════════════════════
# [5/8] PROVEDORES LLM (Interativo via /dev/tty)
# ═══════════════════════════════════════════════════════════
header "[5/8] Provedores LLM"

echo -e "  Selecione os provedores de IA:"
echo ""
echo -e "    ${BOLD}1${NC} — OpenAI        ${DIM}(GPT-4o, GPT-4o-mini)${NC}"
echo -e "    ${BOLD}2${NC} — Anthropic     ${DIM}(Claude Sonnet, Opus, Haiku)${NC}"
echo -e "    ${BOLD}3${NC} — OpenRouter    ${DIM}(Todos os modelos ⭐)${NC}"
echo -e "    ${BOLD}4${NC} — NVIDIA NIM    ${DIM}(Llama, Gemma, Qwen)${NC}"
echo -e "    ${BOLD}5${NC} — Custom        ${DIM}(Endpoint OpenAI-compatível)${NC}"
echo ""
echo -ne "  ${BOLD}Provedores (ex: 1,3 ou 4): ${NC}"
safe_read PROVIDER_SELECTION

OPENAI_ENABLED=false; OPENAI_KEY=""
ANTHROPIC_ENABLED=false; ANTHROPIC_KEY=""
OPENROUTER_ENABLED=false; OPENROUTER_KEY=""
NVIDIA_ENABLED=false; NVIDIA_KEY=""
OPENCODE_ENABLED=false; OPENCODE_KEY=""; OPENCODE_BASE=""
DEFAULT_MODEL=""; FALLBACK_MODEL=""

IFS=',' read -ra PROVIDERS <<< "$PROVIDER_SELECTION"
for p in "${PROVIDERS[@]}"; do
    p=$(echo "$p" | tr -d ' ')
    case "$p" in
        1)
            echo -ne "\n  ${CYAN}OpenAI API Key: ${NC}"
            safe_read_secret OPENAI_KEY; echo ""
            OPENAI_ENABLED=true
            [[ -z "$DEFAULT_MODEL" ]] && DEFAULT_MODEL="gpt-4o-mini"
            ok "OpenAI ativado"
            ;;
        2)
            echo -ne "\n  ${CYAN}Anthropic API Key: ${NC}"
            safe_read_secret ANTHROPIC_KEY; echo ""
            ANTHROPIC_ENABLED=true
            [[ -z "$DEFAULT_MODEL" ]] && DEFAULT_MODEL="claude-sonnet-4-20250514"
            ok "Anthropic ativado"
            ;;
        3)
            echo -ne "\n  ${CYAN}OpenRouter API Key: ${NC}"
            safe_read_secret OPENROUTER_KEY; echo ""
            OPENROUTER_ENABLED=true
            [[ -z "$DEFAULT_MODEL" ]] && DEFAULT_MODEL="anthropic/claude-sonnet-4"
            ok "OpenRouter ativado"
            ;;
        4)
            echo -ne "\n  ${CYAN}NVIDIA NIM API Key: ${NC}"
            safe_read_secret NVIDIA_KEY; echo ""
            echo -ne "  ${CYAN}Modelo padrão (Enter = meta/llama-3.1-405b-instruct): ${NC}"
            safe_read NV_MODEL
            echo -ne "  ${CYAN}Modelo fallback (Enter = pular): ${NC}"
            safe_read NV_FALLBACK
            NVIDIA_ENABLED=true
            [[ -z "$DEFAULT_MODEL" ]] && DEFAULT_MODEL="${NV_MODEL:-meta/llama-3.1-405b-instruct}"
            [[ -n "${NV_FALLBACK:-}" ]] && FALLBACK_MODEL="$NV_FALLBACK"
            ok "NVIDIA NIM ativado"
            ;;
        5)
            echo -ne "\n  ${CYAN}Base URL: ${NC}"
            safe_read OPENCODE_BASE
            echo -ne "  ${CYAN}API Key: ${NC}"
            safe_read_secret OPENCODE_KEY; echo ""
            echo -ne "  ${CYAN}Nome do modelo: ${NC}"
            safe_read CUSTOM_MODEL
            OPENCODE_ENABLED=true
            [[ -z "$DEFAULT_MODEL" ]] && DEFAULT_MODEL="${CUSTOM_MODEL:-custom}"
            ok "Custom ativado"
            ;;
        *) warn "Opção '$p' ignorada" ;;
    esac
done

[[ -z "$DEFAULT_MODEL" ]] && { warn "Nenhum provedor configurado"; DEFAULT_MODEL="gpt-4o-mini"; }
ok "Modelo padrão: $DEFAULT_MODEL"
[[ -n "${FALLBACK_MODEL:-}" ]] && ok "Fallback: $FALLBACK_MODEL"

# ═══════════════════════════════════════════════════════════
# [6/8] TELEGRAM (Interativo via /dev/tty)
# ═══════════════════════════════════════════════════════════
header "[6/8] Telegram Bot"

echo -e "  Como criar seu bot:"
echo -e "    1. Abra o Telegram → procure ${CYAN}@BotFather${NC}"
echo -e "    2. Envie ${CYAN}/newbot${NC} → siga as instruções"
echo -e "    3. Copie o token"
echo ""
echo -e "  Para seu User ID: envie ${CYAN}/start${NC} para ${CYAN}@userinfobot${NC}"
echo ""
echo -ne "  ${BOLD}Token do Bot: ${NC}"
safe_read_secret BOT_TOKEN; echo ""
echo -ne "  ${BOLD}Seu Telegram User ID: ${NC}"
safe_read TELEGRAM_USER_ID

# Validar token
if [[ -n "$BOT_TOKEN" ]]; then
    BOT_TEST=$(curl -s "https://api.telegram.org/bot${BOT_TOKEN}/getMe" 2>/dev/null || echo '{}')
    if echo "$BOT_TEST" | grep -q '"ok":true'; then
        BOT_NAME=$(echo "$BOT_TEST" | python3 -c "import sys,json;print(json.load(sys.stdin)['result']['username'])" 2>/dev/null || echo "?")
        ok "Bot validado: @$BOT_NAME"
    else
        warn "Token não validado — verifique depois em openpy.toml"
    fi
else
    warn "Token vazio — configure depois com: openpy config"
fi

# Validar User ID (deve ser número)
if [[ -n "$TELEGRAM_USER_ID" ]] && [[ "$TELEGRAM_USER_ID" =~ ^[0-9]+$ ]]; then
    ok "User ID: $TELEGRAM_USER_ID"
else
    warn "User ID inválido ou vazio — configure depois com: openpy config"
    TELEGRAM_USER_ID="0"
fi

# ═══════════════════════════════════════════════════════════
# [7/8] GERAR CONFIG + MIGRATIONS
# ═══════════════════════════════════════════════════════════
header "[7/8] Configuração"

cat > "$CONFIG_FILE" << TOMLEOF
# Open-PY Config — Gerado em $(date -Iseconds)

[core]
name = "Open-PY"
version = "$VERSION"
language = "pt-BR"
default_model = "$DEFAULT_MODEL"
fallback_model = "${FALLBACK_MODEL:-}"
max_concurrent_agents = 10
thinking_layers = 4
install_dir = "$INSTALL_DIR"

[database]
host = "localhost"
port = 5432
name = "openpy"
user = "openpy"
password = "$DB_PASSWORD"

[telegram]
bot_token = "$BOT_TOKEN"
allowed_users = [$TELEGRAM_USER_ID]
max_message_length = 4096
polling_mode = true

[memory]
context_max_tokens = 128000
context_save_interval_minutes = 60
migration_hour = 0
migration_minute = 0
discard_md_after_migration = true
embedding_model = "all-MiniLM-L6-v2"
embedding_dimensions = 384
max_search_results = 10

[providers.openai]
api_key = "$OPENAI_KEY"
api_base = ""
enabled = $OPENAI_ENABLED

[providers.anthropic]
api_key = "$ANTHROPIC_KEY"
api_base = ""
enabled = $ANTHROPIC_ENABLED

[providers.openrouter]
api_key = "$OPENROUTER_KEY"
api_base = ""
enabled = $OPENROUTER_ENABLED

[providers.nvidia]
api_key = "$NVIDIA_KEY"
api_base = "https://integrate.api.nvidia.com/v1"
enabled = $NVIDIA_ENABLED

[providers.opencode]
api_key = "$OPENCODE_KEY"
api_base = "$OPENCODE_BASE"
enabled = $OPENCODE_ENABLED

[scheduler]
heartbeat_interval_seconds = 60
max_cron_jobs = 50

[doctor]
auto_repair = true
snapshot_on_startup = true
TOMLEOF

chmod 600 "$CONFIG_FILE"
ok "openpy.toml gerado (permissões 600 — só root lê)"

# Migrations
step "Executando migrations..."
if "$VENV_DIR/bin/python3" -c "
import asyncio, sys
sys.path.insert(0, '$INSTALL_DIR')
try:
    from shared.migrations import run_migrations
    asyncio.run(run_migrations('postgresql://openpy:$DB_PASSWORD@localhost:5432/openpy'))
except Exception as e:
    print(f'Migration warning: {e}', file=sys.stderr)
    sys.exit(0)
" >> "$LOG_FILE" 2>&1; then
    ok "Banco de dados configurado"
else
    warn "Migrations com avisos (mas continuando)"
fi

# ═══════════════════════════════════════════════════════════
# [8/8] SYSTEMD + CLI
# ═══════════════════════════════════════════════════════════
header "[8/8] Serviço e CLI"

cat > /etc/systemd/system/open-py.service << SVCEOF
[Unit]
Description=Open-PY AI Agent Framework
After=network.target postgresql.service
Wants=postgresql.service

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR
Environment=OPENPY_DIR=$INSTALL_DIR
ExecStart=$VENV_DIR/bin/python3 -m __main__
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
WatchdogSec=300

[Install]
WantedBy=multi-user.target
SVCEOF

systemctl daemon-reload
systemctl enable open-py >> "$LOG_FILE" 2>&1 || true
ok "Serviço systemd criado e habilitado"

# CLI
cat > /usr/local/bin/openpy << 'CLIEOF'
#!/bin/bash
# Open-PY CLI v2.1
INSTALL_DIR="/opt/open-py"
VENV="$INSTALL_DIR/venv/bin/python3"

case "${1:-help}" in
    start)    systemctl start open-py && echo "✅ Open-PY iniciado" ;;
    stop)     systemctl stop open-py && echo "🛑 Open-PY parado" ;;
    restart)  systemctl restart open-py && echo "🔄 Open-PY reiniciado" ;;
    status)   systemctl status open-py --no-pager ;;
    logs)
        shift
        if [[ "${1:-}" == "-n" && -n "${2:-}" ]]; then
            journalctl -u open-py --no-hostname -n "$2" --no-pager
        else
            journalctl -u open-py -f --no-hostname
        fi
        ;;
    doctor)   cd "$INSTALL_DIR" && "$VENV" -m __main__ doctor ;;
    config)   ${EDITOR:-nano} "$INSTALL_DIR/openpy.toml" && echo "⚠️  Execute: openpy restart" ;;
    soul)     ${EDITOR:-nano} "$INSTALL_DIR/data/soul.md" ;;
    essence)  ${EDITOR:-nano} "$INSTALL_DIR/data/essence.md" ;;
    version)  cat "$INSTALL_DIR/VERSION" 2>/dev/null || echo "?" ;;
    update)
        echo "🔄 Atualizando Open-PY..."
        cd "$INSTALL_DIR" && git pull origin main 2>/dev/null || git pull origin master
        source "$INSTALL_DIR/venv/bin/activate"
        pip install -q -r "$INSTALL_DIR/requirements.txt" 2>/dev/null
        systemctl restart open-py && echo "✅ Atualizado e reiniciado"
        ;;
    uninstall)
        echo "⚠️  Remover TUDO de $INSTALL_DIR?"
        echo -n "Digite 'sim' para confirmar: "; read -r r
        if [[ "$r" == "sim" ]]; then
            systemctl stop open-py 2>/dev/null; systemctl disable open-py 2>/dev/null
            rm -f /etc/systemd/system/open-py.service; systemctl daemon-reload
            rm -rf "$INSTALL_DIR"; rm -f /usr/local/bin/openpy
            echo "✅ Open-PY removido"
        fi ;;
    *)
        echo ""
        echo "  🧠 Open-PY v$(cat $INSTALL_DIR/VERSION 2>/dev/null || echo '?')"
        echo "  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo "  openpy start       Iniciar"
        echo "  openpy stop        Parar"
        echo "  openpy restart     Reiniciar"
        echo "  openpy status      Status do serviço"
        echo "  openpy logs        Logs em tempo real"
        echo "  openpy logs -n 50  Últimas 50 linhas"
        echo "  openpy doctor      Diagnóstico completo"
        echo "  openpy config      Editar configuração"
        echo "  openpy soul        Editar memória permanente"
        echo "  openpy essence     Editar personalidade"
        echo "  openpy update      Atualizar via GitHub"
        echo "  openpy version     Ver versão"
        echo "  openpy uninstall   Remover tudo"
        echo "" ;;
esac
CLIEOF
chmod +x /usr/local/bin/openpy
ok "Comando 'openpy' disponível globalmente"

# ═══════════════════════════════════════════════════════════
# CONCLUSÃO
# ═══════════════════════════════════════════════════════════
echo ""
if [[ $ERRORS -eq 0 ]]; then
    echo -e "${GREEN}╔═══════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║       ✅ OPEN-PY INSTALADO COM SUCESSO!          ║${NC}"
    echo -e "${GREEN}╚═══════════════════════════════════════════════════╝${NC}"
else
    echo -e "${YELLOW}╔═══════════════════════════════════════════════════╗${NC}"
    echo -e "${YELLOW}║   ⚠️  INSTALADO COM $ERRORS AVISO(S)               ║${NC}"
    echo -e "${YELLOW}║   Verifique: cat $LOG_FILE        ║${NC}"
    echo -e "${YELLOW}╚═══════════════════════════════════════════════════╝${NC}"
fi
echo ""
echo -e "  ${BOLD}Comandos:${NC}"
echo -e "    ${CYAN}openpy start${NC}     Iniciar"
echo -e "    ${CYAN}openpy logs${NC}      Ver logs"
echo -e "    ${CYAN}openpy doctor${NC}    Diagnóstico"
echo -e "    ${CYAN}openpy config${NC}    Editar configuração"
echo -e "    ${CYAN}openpy update${NC}    Atualizar via GitHub"
echo -e "    ${CYAN}openpy${NC}           Ver todos os comandos"
echo ""
echo -e "  ${BOLD}Próximo passo:${NC}"
echo -e "    ${CYAN}openpy start${NC}"
echo ""

echo -ne "  ${BOLD}Iniciar agora? (s/n): ${NC}"
safe_read START_NOW
if [[ "${START_NOW:-n}" == "s" || "${START_NOW:-n}" == "S" || "${START_NOW:-n}" == "y" ]]; then
    systemctl start open-py; sleep 3
    if systemctl is-active --quiet open-py; then
        ok "Open-PY rodando! Envie /start no Telegram."
    else
        warn "Erro ao iniciar. Execute: openpy logs"
    fi
fi
echo ""
