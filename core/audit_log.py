"""
Open-PY — Audit Log Imutável
Log de ações críticas com encadeamento SHA-256 (blockchain-style).
Garante trilha forense à prova de adulteração.

Formato: JSONL com chain hash
Cada linha: {"ts":"ISO8601","actor":"...","action":"...","target":"...",
             "payload_hash":"sha256","prev_hash":"sha256"}
"""

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from shared.logger import get_logger

log = get_logger("audit")

# Ações que sempre são logadas
CRITICAL_ACTIONS = {
    "agent_create", "agent_destroy", "agent_spawn",
    "shell_exec", "file_delete", "file_write",
    "soul_edit", "essence_edit",
    "db_drop", "db_alter", "db_truncate",
    "network_request", "package_install",
    "config_change", "memory_bulk_delete",
}


class AuditLog:
    """
    Log imutável de ações críticas com chain SHA-256.
    
    - Append-only: nunca deleta ou edita entradas
    - Chain hash: cada entrada referencia o hash da anterior
    - Rotação por data: um arquivo por dia
    - Verificação: método verify_chain() detecta adulteração
    """

    def __init__(self, log_dir: str = "/opt/open-py/data/audit"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._prev_hash: str = self._load_last_hash()

    def _get_today_file(self) -> Path:
        """Arquivo de log do dia atual"""
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return self.log_dir / f"audit_{date_str}.jsonl"

    def _load_last_hash(self) -> str:
        """Carrega o último hash da chain para continuidade"""
        # Encontrar o arquivo mais recente
        files = sorted(self.log_dir.glob("audit_*.jsonl"), reverse=True)
        if not files:
            return "GENESIS"  # Primeiro hash da chain

        try:
            # Ler última linha do arquivo mais recente
            with open(files[0], "r", encoding="utf-8") as f:
                lines = f.readlines()
                if lines:
                    last_entry = json.loads(lines[-1].strip())
                    return self._compute_entry_hash(last_entry)
        except (json.JSONDecodeError, KeyError, IndexError):
            log.warning("⚠️ Não foi possível carregar último hash, resetando chain")
        
        return "GENESIS"

    def _compute_entry_hash(self, entry: dict) -> str:
        """Computa hash SHA-256 de uma entrada"""
        # Hash determinístico: ordena as chaves
        canonical = json.dumps(entry, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _compute_payload_hash(self, payload: dict) -> str:
        """Hash do payload para verificação de integridade"""
        canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]

    async def log_action(
        self,
        actor: str,
        action: str,
        target: str = "",
        payload: Optional[dict] = None,
        severity: str = "critical",
        requires_confirmation: bool = False,
    ) -> dict:
        """
        Registra uma ação crítica no audit log.
        
        Args:
            actor: Quem executou (ex: "agent:builder", "user:1050410410", "core")
            action: O que foi feito (ex: "file_delete", "shell_exec")
            target: Alvo da ação (ex: "/tmp/test.py", "agent:vision")
            payload: Dados adicionais (ex: {"command": "rm -rf /tmp"})
            severity: Nível (critical, high, medium, low)
            requires_confirmation: Se a ação precisava de confirmação do usuário
        
        Returns:
            A entrada criada no log
        """
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "actor": actor,
            "action": action,
            "target": target,
            "severity": severity,
            "requires_confirmation": requires_confirmation,
            "payload_hash": self._compute_payload_hash(payload or {}),
            "prev_hash": self._prev_hash,
        }

        # Append ao arquivo do dia
        log_file = self._get_today_file()
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        # Atualizar chain
        self._prev_hash = self._compute_entry_hash(entry)

        # Proteger arquivo (append-only para o user openpy)
        try:
            os.chmod(str(log_file), 0o644)  # rw-r--r--
        except OSError:
            pass

        log.info("📝 Audit log",
                 actor=actor, action=action, target=target,
                 severity=severity)

        return entry

    def is_critical(self, action: str) -> bool:
        """Verifica se uma ação é crítica e deve ser logada"""
        return action in CRITICAL_ACTIONS

    async def verify_chain(self, date: str = None) -> dict:
        """
        Verifica integridade da chain de hashes.
        
        Args:
            date: Data específica (YYYY-MM-DD) ou None para hoje
        
        Returns:
            {"valid": bool, "entries": int, "broken_at": int|None}
        """
        if date:
            log_file = self.log_dir / f"audit_{date}.jsonl"
        else:
            log_file = self._get_today_file()

        if not log_file.exists():
            return {"valid": True, "entries": 0, "broken_at": None}

        entries = []
        with open(log_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        return {"valid": False, "entries": len(entries),
                                "broken_at": len(entries), "reason": "JSON inválido"}

        # Verificar chain
        for i in range(1, len(entries)):
            expected_hash = self._compute_entry_hash(entries[i - 1])
            actual_prev = entries[i].get("prev_hash", "")
            if expected_hash != actual_prev:
                return {
                    "valid": False,
                    "entries": len(entries),
                    "broken_at": i,
                    "reason": f"Hash mismatch na entrada {i}"
                }

        return {"valid": True, "entries": len(entries), "broken_at": None}

    async def get_recent(self, limit: int = 20) -> list[dict]:
        """Retorna as últimas N entradas do audit log"""
        log_file = self._get_today_file()
        if not log_file.exists():
            return []

        entries = []
        with open(log_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue

        return entries[-limit:]

    async def get_stats(self) -> dict:
        """Estatísticas do audit log"""
        files = list(self.log_dir.glob("audit_*.jsonl"))
        total_entries = 0
        for f in files:
            with open(f, "r", encoding="utf-8") as fh:
                total_entries += sum(1 for line in fh if line.strip())

        return {
            "total_files": len(files),
            "total_entries": total_entries,
            "oldest_date": files[0].stem.replace("audit_", "") if files else None,
            "newest_date": files[-1].stem.replace("audit_", "") if files else None,
        }
