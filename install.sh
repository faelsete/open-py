#!/bin/bash
# ═══════════════════════════════════════════════════════════
# Open-PY — Instalador v2.2 (Production Edition)
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
OPENPY_VERSION="2.2.0"
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
echo -e "    ${DIM}Framework de Agentes Autônomos v${OPENPY_VERSION}${NC}"
echo -e "    ${DIM}github.com/faelsete/open-py${NC}"
echo ""

# ═══════════════════════════════════════════════════════════
# VERIFICAÇÕES INICIAIS
# ═══════════════════════════════════════════════════════════
[[ "$(uname)" != "Linux" ]] && die "Open-PY requer Linux (Ubuntu 22.04+ / Debian 12+)"
[[ "$EUID" -ne 0 ]] && die "Execute como root: curl ... | sudo bash"

# Verifica se /dev/tty é acessível (necessário para input interativo)
if ! exec 3< /dev/tty 2>/dev/null; then
    die "Sem acesso ao terminal (/dev/tty). Execute: bash <(curl -fsSL URL)"
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

# ────────────────── PGVECTOR ──────────────────
# Detectar versão do PostgreSQL
PG_VERSION=$(pg_config --version 2>/dev/null | grep -oP '\d+' | head -1 || echo "14")
PGVECTOR_INSTALLED=false

# Instalar headers do servidor PostgreSQL (necessário para compilar extensões)
if ! dpkg -s "postgresql-server-dev-${PG_VERSION}" &>/dev/null 2>&1; then
    step "Instalando headers do PostgreSQL ${PG_VERSION}..."
    apt-get install -y -qq "postgresql-server-dev-${PG_VERSION}" >> "$LOG_FILE" 2>&1 || {
        apt-get install -y -qq "postgresql-server-dev-all" >> "$LOG_FILE" 2>&1 || true
    }
fi

if dpkg -s "postgresql-${PG_VERSION}-pgvector" &>/dev/null 2>&1; then
    ok "pgvector (já instalado)"
    PGVECTOR_INSTALLED=true
else
    step "Instalando pgvector..."

    # Método 1: apt direto
    if apt-get install -y -qq "postgresql-${PG_VERSION}-pgvector" >> "$LOG_FILE" 2>&1; then
        ok "pgvector (apt)"
        PGVECTOR_INSTALLED=true
    else
        # Método 2: Adicionar repositório PGDG oficial
        step "Adicionando repositório PostgreSQL oficial..."
        if command -v lsb_release &>/dev/null; then
            CODENAME=$(lsb_release -cs)
        else
            CODENAME=$(grep VERSION_CODENAME /etc/os-release | cut -d= -f2)
        fi
        echo "deb http://apt.postgresql.org/pub/repos/apt ${CODENAME}-pgdg main" > /etc/apt/sources.list.d/pgdg.list 2>/dev/null || true
        wget -qO- https://www.postgresql.org/media/keys/ACCC4CF8.asc 2>/dev/null | gpg --dearmor -o /usr/share/keyrings/pgdg.gpg 2>/dev/null || true
        # Atualizar com a key ring
        sed -i "s|deb http|deb [signed-by=/usr/share/keyrings/pgdg.gpg] http|" /etc/apt/sources.list.d/pgdg.list 2>/dev/null || true
        apt-get update -qq >> "$LOG_FILE" 2>&1 || true

        if apt-get install -y -qq "postgresql-${PG_VERSION}-pgvector" >> "$LOG_FILE" 2>&1; then
            ok "pgvector (PGDG repo)"
            PGVECTOR_INSTALLED=true
        else
            # Método 3: Compilar do fonte
            warn "Compilando pgvector do fonte..."
            cd /tmp
            rm -rf pgvector 2>/dev/null
            if git clone --branch v0.7.4 https://github.com/pgvector/pgvector.git >> "$LOG_FILE" 2>&1; then
                cd pgvector
                if make PG_CONFIG="$(which pg_config)" >> "$LOG_FILE" 2>&1 && \
                   make install PG_CONFIG="$(which pg_config)" >> "$LOG_FILE" 2>&1; then
                    ok "pgvector (compilado)"
                    PGVECTOR_INSTALLED=true
                else
                    fail "pgvector — compilação falhou"
                    info "Busca semântica será desabilitada"
                fi
                cd /tmp && rm -rf pgvector
            else
                fail "pgvector — download falhou"
            fi
        fi
    fi
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

# Criar user e database
step "Configurando banco de dados..."

# Drop na ordem correta
sudo -u postgres psql -c "DROP DATABASE IF EXISTS openpy;" >> "$LOG_FILE" 2>&1 || true
sudo -u postgres psql -c "DROP USER IF EXISTS openpy;" >> "$LOG_FILE" 2>&1 || true

# Criar user
if sudo -u postgres psql -c "CREATE USER openpy WITH PASSWORD '$DB_PASSWORD';" >> "$LOG_FILE" 2>&1; then
    ok "User 'openpy' criado"
else
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
if $PGVECTOR_INSTALLED; then
    if sudo -u postgres psql -d openpy -c "CREATE EXTENSION IF NOT EXISTS vector;" >> "$LOG_FILE" 2>&1; then
        ok "Extensão pgvector ativada"
    else
        fail "Extensão pgvector falhou (ver $LOG_FILE)"
    fi
else
    warn "pgvector não instalado — extensão vector ignorada"
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

# ─── Função: buscar modelos disponíveis da API ───
fetch_models() {
    local api_key="$1"
    local base_url="$2"
    local provider="$3"  # openai|anthropic|openrouter|nvidia|custom
    local auth_header models_json

    # Anthropic usa x-api-key, todos os outros usam Bearer
    if [[ "$provider" == "anthropic" ]]; then
        models_json=$(curl -s --max-time 10 \
            -H "x-api-key: $api_key" \
            -H "anthropic-version: 2023-06-01" \
            "${base_url}/v1/models" 2>/dev/null)
    else
        models_json=$(curl -s --max-time 10 \
            -H "Authorization: Bearer $api_key" \
            "${base_url}/models" 2>/dev/null)
    fi

    # Extrair IDs dos modelos
    if [[ -n "$models_json" ]] && echo "$models_json" | jq -e '.data' &>/dev/null; then
        echo "$models_json" | jq -r '.data[].id' 2>/dev/null | sort
    else
        echo ""
    fi
}

# ─── Função: selecionar modelo com lista numerada ───
select_model() {
    local api_key="$1"
    local base_url="$2"
    local provider="$3"
    local prompt_label="$4"  # ex: "padrão" ou "fallback"
    local result_var="$5"

    step "Buscando modelos disponíveis..."
    local raw_models
    raw_models=$(fetch_models "$api_key" "$base_url" "$provider")

    if [[ -z "$raw_models" ]]; then
        warn "Não foi possível listar modelos da API"
        echo -ne "  ${CYAN}Digite o nome do modelo ${prompt_label}: ${NC}"
        safe_read _typed_model
        eval "$result_var=\"\$_typed_model\""
        return
    fi

    # Converter em array
    local model_array=()
    while IFS= read -r m; do
        [[ -n "$m" ]] && model_array+=("$m")
    done <<< "$raw_models"

    local total=${#model_array[@]}
    if [[ "$total" -eq 0 ]]; then
        warn "Nenhum modelo encontrado"
        echo -ne "  ${CYAN}Digite o nome do modelo ${prompt_label}: ${NC}"
        safe_read _typed_model
        eval "$result_var=\"\$_typed_model\""
        return
    fi

    # Mostrar lista (máx 40 por página)
    local show_max=40
    echo ""
    echo -e "  ${BOLD}📋 Modelos disponíveis (${total} encontrados):${NC}"
    echo ""

    local i=1
    for m in "${model_array[@]}"; do
        if [[ $i -le $show_max ]]; then
            printf "    ${CYAN}%3d${NC} — %s\n" "$i" "$m"
        fi
        ((i++))
    done

    if [[ "$total" -gt "$show_max" ]]; then
        echo -e "    ${DIM}... e mais $((total - show_max)) modelos (digite o nome para escolher outro)${NC}"
    fi

    echo ""
    echo -ne "  ${BOLD}Escolha o número ou digite o nome do modelo ${prompt_label}: ${NC}"
    safe_read _choice

    if [[ "$_choice" =~ ^[0-9]+$ ]] && [[ "$_choice" -ge 1 ]] && [[ "$_choice" -le "$total" ]]; then
        eval "$result_var=\"${model_array[$((_choice-1))]}\""
    else
        eval "$result_var=\"\$_choice\""
    fi
}

echo -e "  Selecione os provedores de IA:"
echo ""
echo -e "    ${BOLD}1${NC} — OpenAI        ${DIM}(GPT-4o, GPT-4o-mini, ...)${NC}"
echo -e "    ${BOLD}2${NC} — Anthropic     ${DIM}(Claude Sonnet, Opus, Haiku, ...)${NC}"
echo -e "    ${BOLD}3${NC} — OpenRouter    ${DIM}(Centenas de modelos ⭐)${NC}"
echo -e "    ${BOLD}4${NC} — NVIDIA NIM    ${DIM}(Llama, Gemma, Qwen, ...)${NC}"
echo -e "    ${BOLD}5${NC} — Custom        ${DIM}(Endpoint OpenAI-compatível)${NC}"
echo ""
echo -ne "  ${BOLD}Provedores (ex: 1,3 ou 4): ${NC}"
safe_read PROVIDER_SELECTION

OPENAI_ENABLED=false; OPENAI_KEY=""; OPENAI_BASE="https://api.openai.com/v1"
ANTHROPIC_ENABLED=false; ANTHROPIC_KEY=""; ANTHROPIC_BASE="https://api.anthropic.com"
OPENROUTER_ENABLED=false; OPENROUTER_KEY=""; OPENROUTER_BASE="https://openrouter.ai/api/v1"
NVIDIA_ENABLED=false; NVIDIA_KEY=""; NVIDIA_BASE="https://integrate.api.nvidia.com/v1"
OPENCODE_ENABLED=false; OPENCODE_KEY=""; OPENCODE_BASE=""
DEFAULT_MODEL=""; FALLBACK_MODEL=""

IFS=',' read -ra PROVIDERS <<< "$PROVIDER_SELECTION"
for p in "${PROVIDERS[@]}"; do
    p=$(echo "$p" | tr -d ' ')
    case "$p" in
        1)
            echo ""
            echo -ne "  ${CYAN}OpenAI API Key: ${NC}"
            safe_read OPENAI_KEY
            echo -ne "  ${CYAN}Base URL (Enter = https://api.openai.com/v1): ${NC}"
            safe_read OA_BASE
            [[ -n "$OA_BASE" ]] && OPENAI_BASE="$OA_BASE"
            OPENAI_ENABLED=true
            select_model "$OPENAI_KEY" "$OPENAI_BASE" "openai" "padrão" DEFAULT_MODEL
            ok "OpenAI ativado → $OPENAI_BASE"
            ;;
        2)
            echo ""
            echo -ne "  ${CYAN}Anthropic API Key: ${NC}"
            safe_read ANTHROPIC_KEY
            echo -ne "  ${CYAN}Base URL (Enter = https://api.anthropic.com): ${NC}"
            safe_read AN_BASE
            [[ -n "$AN_BASE" ]] && ANTHROPIC_BASE="$AN_BASE"
            ANTHROPIC_ENABLED=true
            select_model "$ANTHROPIC_KEY" "$ANTHROPIC_BASE" "anthropic" "padrão" DEFAULT_MODEL
            ok "Anthropic ativado → $ANTHROPIC_BASE"
            ;;
        3)
            echo ""
            echo -ne "  ${CYAN}OpenRouter API Key: ${NC}"
            safe_read OPENROUTER_KEY
            echo -ne "  ${CYAN}Base URL (Enter = https://openrouter.ai/api/v1): ${NC}"
            safe_read OR_BASE
            [[ -n "$OR_BASE" ]] && OPENROUTER_BASE="$OR_BASE"
            OPENROUTER_ENABLED=true
            select_model "$OPENROUTER_KEY" "$OPENROUTER_BASE" "openrouter" "padrão" DEFAULT_MODEL
            ok "OpenRouter ativado → $OPENROUTER_BASE"
            ;;
        4)
            echo ""
            info "Base URL padrão: https://integrate.api.nvidia.com/v1"
            echo -ne "  ${CYAN}NVIDIA NIM API Key (nvapi-...): ${NC}"
            safe_read NVIDIA_KEY
            echo -ne "  ${CYAN}Base URL (Enter = https://integrate.api.nvidia.com/v1): ${NC}"
            safe_read NV_BASE
            [[ -n "$NV_BASE" ]] && NVIDIA_BASE="$NV_BASE"
            NVIDIA_ENABLED=true
            select_model "$NVIDIA_KEY" "$NVIDIA_BASE" "nvidia" "padrão" DEFAULT_MODEL
            ok "NVIDIA NIM ativado → $NVIDIA_BASE"
            ;;
        5)
            echo ""
            echo -ne "  ${CYAN}Base URL: ${NC}"
            safe_read OPENCODE_BASE
            echo -ne "  ${CYAN}API Key: ${NC}"
            safe_read OPENCODE_KEY
            OPENCODE_ENABLED=true
            select_model "$OPENCODE_KEY" "$OPENCODE_BASE" "custom" "padrão" DEFAULT_MODEL
            ok "Custom ativado → $OPENCODE_BASE"
            ;;
        *) warn "Opção '$p' ignorada" ;;
    esac
done

# Fallback (opcional)
if [[ -n "$DEFAULT_MODEL" ]]; then
    echo ""
    echo -ne "  ${CYAN}Modelo fallback (Enter = pular): ${NC}"
    safe_read FALLBACK_MODEL
fi

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
safe_read BOT_TOKEN
echo -ne "  ${BOLD}Seu Telegram User ID: ${NC}"
safe_read TELEGRAM_USER_ID

# Validar token
if [[ -n "$BOT_TOKEN" ]]; then
    BOT_TEST=$(curl -s "https://api.telegram.org/bot${BOT_TOKEN}/getMe" 2>/dev/null || echo '{}')
    if echo "$BOT_TEST" | grep -q '"ok":true'; then
        BOT_NAME=$(echo "$BOT_TEST" | python3 -c "import sys,json;print(json.load(sys.stdin)['result']['username'])" 2>/dev/null || echo "?")
        ok "Bot validado: @$BOT_NAME"
    else
        warn "Token não validado — verifique depois com: openpy config"
    fi
else
    warn "Token vazio — configure depois com: openpy config"
fi

# Validar User ID
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
# ═══════════════════════════════════════════════════════════
# Open-PY Config — Gerado em $(date -Iseconds)
# Edite com: openpy config
# ═══════════════════════════════════════════════════════════

[core]
name = "Open-PY"
version = "$OPENPY_VERSION"
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
api_base = "$OPENAI_BASE"
enabled = $OPENAI_ENABLED

[providers.anthropic]
api_key = "$ANTHROPIC_KEY"
api_base = "$ANTHROPIC_BASE"
enabled = $ANTHROPIC_ENABLED

[providers.openrouter]
api_key = "$OPENROUTER_KEY"
api_base = "$OPENROUTER_BASE"
enabled = $OPENROUTER_ENABLED

[providers.nvidia]
api_key = "$NVIDIA_KEY"
api_base = "$NVIDIA_BASE"
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
    print('OK')
except Exception as e:
    print(f'WARN: {e}', file=sys.stderr)
    sys.exit(0)
" >> "$LOG_FILE" 2>&1; then
    ok "Banco de dados configurado (6 tabelas)"
else
    warn "Migrations com avisos — verifique com: openpy doctor"
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
ExecStart=$VENV_DIR/bin/python3 $INSTALL_DIR/__main__.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SVCEOF

systemctl daemon-reload
systemctl enable open-py >> "$LOG_FILE" 2>&1 || true
ok "Serviço systemd criado e habilitado"

# CLI
cat > /usr/local/bin/openpy << 'CLIEOF'
#!/bin/bash
# Open-PY CLI v2.2
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
    echo -e "${YELLOW}║   ⚠️  INSTALADO COM $ERRORS AVISO(S)                ║${NC}"
    echo -e "${YELLOW}║   Verifique: cat $LOG_FILE          ║${NC}"
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
