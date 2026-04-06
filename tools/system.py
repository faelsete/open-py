"""
Open-PY v4.0 — System Tools
Download de arquivos, instalação de pacotes, info do sistema.
"""

import asyncio
import json
import os
import platform

import aiohttp
import psutil

from shared.logger import get_logger

log = get_logger("system-tools")


async def download_file(url: str, output_path: str) -> str:
    """Faz download de um arquivo da internet"""
    try:
        os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)

        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=120)) as resp:
                if resp.status != 200:
                    return f'{{"error": "HTTP {resp.status}"}}'

                total = int(resp.headers.get("content-length", 0))
                downloaded = 0

                with open(output_path, "wb") as f:
                    async for chunk in resp.content.iter_chunked(8192):
                        f.write(chunk)
                        downloaded += len(chunk)

                size_mb = downloaded / (1024 * 1024)
                return f"Download concluído: {output_path} ({size_mb:.1f} MB)"

    except Exception as e:
        return f'{{"error": "Falha no download: {e}"}}'


async def pip_install(package: str) -> str:
    """Instala um pacote Python via pip"""
    # Sanitizar: só permitir nomes válidos de pacotes
    if not all(c.isalnum() or c in "-_.[]=<>!" for c in package):
        return '{"error": "Nome de pacote inválido"}'

    proc = await asyncio.create_subprocess_exec(
        "pip", "install", package,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=120
        )
        if proc.returncode == 0:
            return f"✅ Pacote instalado: {package}"
        else:
            return f'{{"error": "{stderr.decode(errors="replace")[:500]}"}}'
    except asyncio.TimeoutError:
        proc.kill()
        return f'{{"error": "Timeout instalando {package}"}}'


async def system_info() -> str:
    """Retorna informações do sistema (RAM, CPU, disco, GPU)"""
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")

    info = {
        "os": platform.system(),
        "os_version": platform.version(),
        "python": platform.python_version(),
        "cpu_cores": psutil.cpu_count(),
        "cpu_percent": psutil.cpu_percent(interval=0.5),
        "ram_total_gb": round(mem.total / (1024**3), 1),
        "ram_used_gb": round(mem.used / (1024**3), 1),
        "ram_percent": mem.percent,
        "disk_total_gb": round(disk.total / (1024**3), 1),
        "disk_used_gb": round(disk.used / (1024**3), 1),
        "disk_percent": disk.percent,
    }

    # GPU info (NVIDIA)
    try:
        proc = await asyncio.create_subprocess_exec(
            "nvidia-smi", "--query-gpu=name,memory.total,memory.used,temperature.gpu",
            "--format=csv,noheader,nounits",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
        if proc.returncode == 0:
            parts = stdout.decode().strip().split(", ")
            if len(parts) >= 4:
                info["gpu"] = {
                    "name": parts[0],
                    "vram_total_mb": int(parts[1]),
                    "vram_used_mb": int(parts[2]),
                    "temperature_c": int(parts[3]),
                }
    except Exception:
        pass

    return json.dumps(info, ensure_ascii=False, indent=2)


async def move_file(source: str, destination: str) -> str:
    """Move ou renomeia um arquivo"""
    import shutil
    try:
        os.makedirs(os.path.dirname(destination) if os.path.dirname(destination) else ".", exist_ok=True)
        shutil.move(source, destination)
        return f"Movido: {source} → {destination}"
    except Exception as e:
        return f'{{"error": "Falha ao mover: {e}"}}'


async def copy_file(source: str, destination: str) -> str:
    """Copia um arquivo"""
    import shutil
    try:
        os.makedirs(os.path.dirname(destination) if os.path.dirname(destination) else ".", exist_ok=True)
        shutil.copy2(source, destination)
        return f"Copiado: {source} → {destination}"
    except Exception as e:
        return f'{{"error": "Falha ao copiar: {e}"}}'


async def find_files(directory: str, pattern: str = "*") -> str:
    """Busca arquivos recursivamente por padrão glob"""
    import glob
    try:
        matches = glob.glob(os.path.join(directory, "**", pattern), recursive=True)
        if len(matches) > 100:
            matches = matches[:100]
        return json.dumps(matches, ensure_ascii=False)
    except Exception as e:
        return f'{{"error": "{e}"}}'
