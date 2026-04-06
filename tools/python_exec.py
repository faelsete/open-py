"""
Open-PY v4.0 — Python Executor
Executa código Python arbitrário em subprocess isolado.
⚠️ TOOL PERIGOSA — Restrita a agentes com can_exec_commands=True.
"""

import asyncio
import json
import tempfile
import os

from shared.logger import get_logger

log = get_logger("python-exec")


async def python_exec(code: str, timeout: int = 30) -> str:
    """Executa código Python em subprocess isolado e retorna stdout+stderr"""
    # Criar arquivo temporário com o código
    tmp_dir = tempfile.mkdtemp(prefix="openpy_exec_")
    script_path = os.path.join(tmp_dir, "script.py")

    try:
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(code)

        # Executar em subprocess isolado
        proc = await asyncio.create_subprocess_exec(
            "python3", script_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=tmp_dir,
            # Não herdar variáveis sensíveis
            env={
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                "HOME": tmp_dir,
                "PYTHONPATH": "",
                "LANG": "en_US.UTF-8",
            }
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )

            result = {
                "stdout": stdout.decode(errors='replace').strip(),
                "stderr": stderr.decode(errors='replace').strip(),
                "returncode": proc.returncode,
                "success": proc.returncode == 0,
            }

            # Limitar output
            if len(result["stdout"]) > 10000:
                result["stdout"] = result["stdout"][:10000] + "\n[...output truncado...]"
            if len(result["stderr"]) > 5000:
                result["stderr"] = result["stderr"][:5000] + "\n[...truncado...]"

            return json.dumps(result, ensure_ascii=False)

        except asyncio.TimeoutError:
            proc.kill()
            return json.dumps({
                "stdout": "",
                "stderr": f"Timeout: execução excedeu {timeout}s",
                "returncode": -1,
                "success": False,
            })

    except Exception as e:
        return json.dumps({
            "stdout": "",
            "stderr": str(e),
            "returncode": -1,
            "success": False,
        })

    finally:
        # Limpar arquivo temporário
        try:
            os.unlink(script_path)
            os.rmdir(tmp_dir)
        except Exception:
            pass
