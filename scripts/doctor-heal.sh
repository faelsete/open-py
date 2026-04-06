#!/bin/bash
# Open-PY — Doctor Self-Healing Script
# Roda via cron ou systemd timer a cada 5 minutos.
# Verifica saúde do sistema e repara automaticamente.

set -euo pipefail

INSTALL_DIR="/opt/open-py"
SERVICE_NAME="open-py"
LOG_FILE="${INSTALL_DIR}/data/doctor.log"
PID_FILE="${INSTALL_DIR}/data/openpy.pid"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# ============================================
# CHECK 1: Serviço rodando?
# ============================================
check_service() {
    if ! systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
        log "❌ Serviço parado — reiniciando..."
        systemctl restart "$SERVICE_NAME"
        sleep 5
        if systemctl is-active --quiet "$SERVICE_NAME"; then
            log "✅ Serviço reiniciado com sucesso"
        else
            log "🔴 FALHA ao reiniciar serviço"
            return 1
        fi
    fi
}

# ============================================
# CHECK 2: Processo Python vivo?
# ============================================
check_process() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if ! kill -0 "$PID" 2>/dev/null; then
            log "❌ PID $PID morto — reiniciando serviço..."
            systemctl restart "$SERVICE_NAME"
        fi
    fi
}

# ============================================
# CHECK 3: PostgreSQL acessível?
# ============================================
check_database() {
    if ! pg_isready -q 2>/dev/null; then
        log "❌ PostgreSQL inacessível — reiniciando..."
        systemctl restart postgresql
        sleep 3
    fi
}

# ============================================
# CHECK 4: Disco cheio? (> 90%)
# ============================================
check_disk() {
    USAGE=$(df "$INSTALL_DIR" | awk 'NR==2 {print $5}' | tr -d '%')
    if [ "$USAGE" -gt 90 ]; then
        log "⚠️ Disco em ${USAGE}% — limpando logs antigos..."
        find "$INSTALL_DIR/data/audit" -name "*.jsonl" -mtime +30 -delete 2>/dev/null
        find "$INSTALL_DIR/data" -name "*.log" -mtime +7 -exec truncate -s 0 {} \; 2>/dev/null
        log "✅ Limpeza concluída"
    fi
}

# ============================================
# CHECK 5: RAM OK? (< 85%)
# ============================================
check_memory() {
    MEM_PCT=$(free | awk 'NR==2 {printf "%.0f", $3/$2*100}')
    if [ "$MEM_PCT" -gt 85 ]; then
        log "⚠️ RAM em ${MEM_PCT}% — reiniciando serviço para liberar..."
        systemctl restart "$SERVICE_NAME"
        sleep 5
        log "✅ Serviço reiniciado (RAM liberada)"
    fi
}

# ============================================
# CHECK 6: Logs enormes?
# ============================================
check_logs() {
    for logf in "$INSTALL_DIR"/data/*.log; do
        if [ -f "$logf" ]; then
            SIZE=$(stat -c%s "$logf" 2>/dev/null || echo 0)
            if [ "$SIZE" -gt 104857600 ]; then  # > 100MB
                log "⚠️ Log $(basename $logf) com $(( SIZE / 1048576 ))MB — truncando..."
                tail -c 10485760 "$logf" > "${logf}.tmp" && mv "${logf}.tmp" "$logf"
            fi
        fi
    done
}

# ============================================
# EXECUÇÃO
# ============================================
log "🔍 Doctor check iniciando..."

check_service
check_process
check_database
check_disk
check_memory
check_logs

log "✅ Doctor check completo — sistema saudável"
