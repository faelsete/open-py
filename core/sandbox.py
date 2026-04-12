"""
Open-PY v5.0 — Sandbox
Execução isolada de comandos via Bubblewrap (bwrap).

Features:
- Filesystem readonly por padrão, com bind-mounts explícitos
- Network isolation (--unshare-net por padrão)
- PID/IPC namespace isolation
- Timeout forçado com SIGKILL
- Fallback para execução direta se bwrap não disponível (dev/Windows)

Bubblewrap já é instalado pelo install.sh — este módulo integra no código.
"""

import asyncio
import shutil
from dataclasses import dataclass, field
from typing import Optional

from shared.logger import get_logger

log = get_logger("sandbox")


@dataclass
class SandboxResult:
    """Resultado de execução sandboxed."""
    stdout: str = ""
    stderr: str = ""
    returncode: int = -1
    timed_out: bool = False
    sandboxed: bool = False
    error: Optional[str] = None


class BubblewrapSandbox:
    """
    Execução isolada de comandos via Bubblewrap.

    Modelo de segurança:
    - Filesystem: / montado readonly, paths específicos com bind rw
    - Network: desabilitada por padrão
    - PID: namespace isolado (processo não vê outros processos)
    - User: namespace separado (sem cap_sys_admin)
    - Timeout: hard kill após N segundos
    """

    def __init__(self):
        self._bwrap_path: Optional[str] = shutil.which("bwrap")
        if self._bwrap_path:
            log.info("✅ Bubblewrap disponível", path=self._bwrap_path)
        else:
            log.warning("⚠️ Bubblewrap não encontrado — modo fallback (sem sandbox)")

    @property
    def available(self) -> bool:
        """Verifica se bwrap está disponível."""
        return self._bwrap_path is not None

    async def execute(
        self,
        command: str,
        allowed_paths: Optional[list[str]] = None,
        network: bool = False,
        timeout: int = 30,
        env: Optional[dict[str, str]] = None,
    ) -> SandboxResult:
        """
        Executa comando em sandbox isolada.

        Args:
            command: Comando shell a executar
            allowed_paths: Caminhos com acesso read-write (bind-mount)
            network: Se True, permite acesso à rede
            timeout: Timeout em segundos antes de SIGKILL
            env: Variáveis de ambiente adicionais

        Returns:
            SandboxResult com stdout, stderr, returncode
        """
        if not self._bwrap_path:
            return await self._fallback_execute(command, timeout)

        try:
            bwrap_cmd = self._build_bwrap_command(
                command=command,
                allowed_paths=allowed_paths or [],
                network=network,
                env=env,
            )

            proc = await asyncio.create_subprocess_shell(
                bwrap_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
                return SandboxResult(
                    stdout=stdout.decode(errors="replace"),
                    stderr=stderr.decode(errors="replace"),
                    returncode=proc.returncode or 0,
                    sandboxed=True,
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return SandboxResult(
                    stderr=f"Timeout ({timeout}s) — processo encerrado",
                    returncode=-1,
                    timed_out=True,
                    sandboxed=True,
                )

        except Exception as e:
            log.error("❌ Sandbox falhou, tentando fallback", error=str(e))
            return await self._fallback_execute(command, timeout)

    def _build_bwrap_command(
        self,
        command: str,
        allowed_paths: list[str],
        network: bool = False,
        env: Optional[dict[str, str]] = None,
    ) -> str:
        """Monta comando bwrap com sandboxing apropriado."""
        parts: list[str] = [str(self._bwrap_path)]

        # Filesystem: readonly root
        parts.extend(["--ro-bind", "/", "/"])

        # Bind-mount paths com read-write
        for path in allowed_paths:
            parts.extend(["--bind", path, path])

        # tmpfs para /tmp (sandbox tem seu próprio /tmp)
        parts.extend(["--tmpfs", "/tmp"])

        # Proc e dev
        parts.extend(["--proc", "/proc"])
        parts.extend(["--dev", "/dev"])

        # Namespace isolation
        parts.append("--unshare-pid")
        parts.append("--unshare-ipc")
        parts.append("--new-session")
        parts.append("--die-with-parent")

        # Network
        if not network:
            parts.append("--unshare-net")

        # Environment
        if env:
            for key, value in env.items():
                parts.extend(["--setenv", key, value])

        # PATH padrão
        parts.extend(["--setenv", "PATH", "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"])
        parts.extend(["--setenv", "HOME", "/tmp"])

        # Comando
        parts.extend(["--", "sh", "-c", command])

        return " ".join(parts)

    async def _fallback_execute(self, command: str, timeout: int) -> SandboxResult:
        """Execução direta sem sandbox (fallback para dev/Windows)."""
        log.warning("⚠️ Executando SEM sandbox (fallback)", command=command[:80])

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
                return SandboxResult(
                    stdout=stdout.decode(errors="replace"),
                    stderr=stderr.decode(errors="replace"),
                    returncode=proc.returncode or 0,
                    sandboxed=False,
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return SandboxResult(
                    stderr=f"Timeout ({timeout}s)",
                    returncode=-1,
                    timed_out=True,
                    sandboxed=False,
                )

        except Exception as e:
            return SandboxResult(
                returncode=-1,
                error=str(e),
                sandboxed=False,
            )
