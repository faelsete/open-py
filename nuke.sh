#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# Open-PY Nuclear Reset — Limpa TUDO e reinstala do zero
# Uso: openpy nuke  OU  sudo bash nuke.sh
# ═══════════════════════════════════════════════════════════════

set -euo pipefail

RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

INSTALL_DIR="/opt/open-py"

echo ""
echo -e "${RED}╔═══════════════════════════════════════════════════╗${NC}"
echo -e "${RED}║          ☢️  OPEN-PY NUCLEAR RESET  ☢️            ║${NC}"
echo -e "${RED}║                                                   ║${NC}"
echo -e "${RED}║  ISSO VAI DESTRUIR:                               ║${NC}"
echo -e "${RED}║  • Banco de dados (DROP DATABASE openpy)          ║${NC}"
echo -e "${RED}║  • Todas as memórias (RAM + MD + PostgreSQL)      ║${NC}"
echo -e "${RED}║  • Logs, audit trail, backups                     ║${NC}"
echo -e "${RED}║  • Configurações (openpy.toml)                    ║${NC}"
echo -e "${RED}║  • Virtual environment (venv)                     ║${NC}"
echo -e "${RED}║  • Serviço systemd                                ║${NC}"
echo -e "${RED}║  • CLI global (/usr/local/bin/openpy)             ║${NC}"
echo -e "${RED}║                                                   ║${NC}"
echo -e "${RED}║  ⚠️  NÃO há como desfazer isso!                   ║${NC}"
echo -e "${RED}╚═══════════════════════════════════════════════════╝${NC}"
echo ""

# Confirmação tripla
echo -e "${YELLOW}Digite ${BOLD}NUKE${NC}${YELLOW} para confirmar a destruição total:${NC}"
read -r confirmation
if [[ "$confirmation" != "NUKE" ]]; then
    echo -e "${GREEN}Cancelado. Nada foi alterado.${NC}"
    exit 0
fi

echo -e "${YELLOW}Tem CERTEZA? Digite ${BOLD}SIM${NC}${YELLOW} para confirmar:${NC}"
read -r confirmation2
if [[ "$confirmation2" != "SIM" ]]; then
    echo -e "${GREEN}Cancelado. Nada foi alterado.${NC}"
    exit 0
fi

echo ""
echo -e "${RED}☢️  Iniciando destruição em 5 segundos...${NC}"
echo -e "${RED}   Ctrl+C para cancelar AGORA${NC}"
sleep 5

echo ""
echo -e "${CYAN}[1/7] Parando serviço...${NC}"
systemctl stop open-py 2>/dev/null || true
systemctl disable open-py 2>/dev/null || true
rm -f /etc/systemd/system/open-py.service
systemctl daemon-reload 2>/dev/null || true
echo -e "${GREEN}  ✅ Serviço removido${NC}"

echo -e "${CYAN}[2/7] Destruindo banco de dados...${NC}"
if command -v psql &>/dev/null; then
    sudo -u postgres psql -c "DROP DATABASE IF EXISTS openpy;" 2>/dev/null || true
    sudo -u postgres psql -c "DROP USER IF EXISTS openpy;" 2>/dev/null || true
    echo -e "${GREEN}  ✅ Database 'openpy' e user 'openpy' removidos${NC}"
else
    echo -e "${YELLOW}  ⚠️ PostgreSQL não encontrado, pulando${NC}"
fi

echo -e "${CYAN}[3/7] Removendo dados persistentes...${NC}"
if [[ -d "$INSTALL_DIR/data" ]]; then
    # Listar o que será apagado
    echo -e "  Apagando:"
    echo -e "    📁 data/memory/     (todas as memórias)"
    echo -e "    📁 data/audit/      (audit trail)"
    echo -e "    📁 data/agents/     (dados de agentes)"
    echo -e "    📁 data/media/      (fotos/áudio/vídeo)"
    echo -e "    📁 data/backups/    (backups)"
    echo -e "    📁 data/logs/       (logs)"
    echo -e "    📁 data/tools/      (ferramentas custom)"
    echo -e "    📁 data/identity_versions/ (versões de soul/essence)"
    echo -e "    📄 data/soul.md     (memória permanente)"
    echo -e "    📄 data/essence.md  (personalidade)"
    rm -rf "$INSTALL_DIR/data"
    echo -e "${GREEN}  ✅ Dados removidos${NC}"
else
    echo -e "${YELLOW}  ⚠️ Diretório data/ não encontrado${NC}"
fi

echo -e "${CYAN}[4/7] Removendo virtual environment...${NC}"
if [[ -d "$INSTALL_DIR/venv" ]]; then
    rm -rf "$INSTALL_DIR/venv"
    echo -e "${GREEN}  ✅ venv removido${NC}"
else
    echo -e "${YELLOW}  ⚠️ venv não encontrado${NC}"
fi

echo -e "${CYAN}[5/7] Removendo configuração...${NC}"
rm -f "$INSTALL_DIR/openpy.toml"
echo -e "${GREEN}  ✅ openpy.toml removido${NC}"

echo -e "${CYAN}[6/7] Removendo CLI global...${NC}"
rm -f /usr/local/bin/openpy
echo -e "${GREEN}  ✅ /usr/local/bin/openpy removido${NC}"

echo -e "${CYAN}[7/7] Limpando cache e PIDs...${NC}"
rm -rf "$INSTALL_DIR/__pycache__"
rm -rf "$INSTALL_DIR/core/__pycache__"
rm -rf "$INSTALL_DIR/memory/__pycache__"
rm -rf "$INSTALL_DIR/agents/__pycache__"
rm -rf "$INSTALL_DIR/telegram_bot/__pycache__"
rm -rf "$INSTALL_DIR/shared/__pycache__"
rm -rf "$INSTALL_DIR/providers/__pycache__"
rm -rf "$INSTALL_DIR/tools/__pycache__"
rm -rf "$INSTALL_DIR/scheduler/__pycache__"
rm -rf "$INSTALL_DIR/doctor/__pycache__"
rm -f /tmp/openpy_*.pid 2>/dev/null || true
echo -e "${GREEN}  ✅ Cache limpo${NC}"

echo ""
echo -e "${GREEN}╔═══════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║  ✅ NUCLEAR RESET COMPLETO                        ║${NC}"
echo -e "${GREEN}║                                                   ║${NC}"
echo -e "${GREEN}║  Tudo foi removido:                               ║${NC}"
echo -e "${GREEN}║  • Banco de dados (DROP DATABASE openpy)          ║${NC}"
echo -e "${GREEN}║  • Memórias, logs, audit, backups                 ║${NC}"
echo -e "${GREEN}║  • Configuração, venv, serviço, CLI               ║${NC}"
echo -e "${GREEN}║                                                   ║${NC}"
echo -e "${GREEN}║  O código-fonte (/opt/open-py/*.py) foi MANTIDO!  ║${NC}"
echo -e "${GREEN}║                                                   ║${NC}"
echo -e "${GREEN}║  Para reinstalar:                                 ║${NC}"
echo -e "${GREEN}║  cd /opt/open-py && sudo bash install.sh          ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════════════════╝${NC}"
echo ""

# Mostrar versão git para rollback
echo -e "${CYAN}📌 Versão atual do código:${NC}"
cd "$INSTALL_DIR" 2>/dev/null && git log --oneline -1 2>/dev/null || echo "  (git não disponível)"
echo ""
echo -e "${CYAN}🔄 Para voltar a uma versão anterior:${NC}"
echo -e "  git tag -l        # ver versões disponíveis"
echo -e "  git checkout v2.2.0  # voltar para v2.2.0"
echo -e "  sudo bash install.sh # reinstalar"
echo ""
