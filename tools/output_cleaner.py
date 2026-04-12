"""
Open-PY v5.1 — Output Cleaner (RTK-style)

Filtra ruído de outputs de CLI/Python antes de enviar ao LLM.
Inspirado no Rust Token Killer (RTK):
  - Remove linhas repetitivas (progress bars, spinners, logs verbose)
  - Trunca outputs enormes de forma inteligente (cabeça + cauda)
  - Remove ANSI escape codes
  - Comprime outputs de testes (mostra só falhas, omite passes)
  - Salva 60-90% de tokens em outputs de CLI

Uso:
    from tools.output_cleaner import clean_output
    cleaned = clean_output(raw_output, max_lines=100)
"""

import re
from typing import Optional

# ============================================
# PADRÕES DE RUÍDO
# ============================================

# ANSI escape codes (cores, cursor, etc)
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]|\x1b\].*?\x07")

# Progress bars e spinners
_PROGRESS_RE = re.compile(
    r"^.*("
    r"\d+%\s*\|[█▓▒░\s]*\|"   # tqdm/rich bars
    r"|[\|/\-\\]\s*\d+%"       # spinner + percent
    r"|\.{3,}"                  # linhas de pontilhamento
    r"|⠋|⠙|⠹|⠸|⠼|⠴|⠦|⠧|⠇|⠏"  # braille spinners
    r"|Downloading.*\d+.*%"    # download bars
    r"|Collecting\s+"          # pip collecting
    r"|Installing\s+"          # pip installing
    r").*$",
    re.MULTILINE,
)

# Linhas de log repetitivas (timestamps, PIDs, etc.)
_LOG_NOISE_RE = re.compile(
    r"^("
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}"  # timestamps ISO
    r"|WARNING:.*:.*"           # Python warnings verbosos
    r"|DEBUG:.*:.*"             # Debug logs
    r"|INFO:.*:.*"              # Info logs genéricos
    r")\s*$",
    re.MULTILINE,
)

# Linhas de teste que passaram (pytest, unittest)
_TEST_PASS_RE = re.compile(
    r"^("
    r".*PASSED.*$"             # pytest PASSED
    r"|.*\.\.\.\s*ok\s*$"      # unittest ok
    r"|.*✓.*$"                 # checkmark passes
    r"|test_\w+\s+\.{1,}\s*$"  # test_name .....
    r")",
    re.MULTILINE,
)

# Separadores decorativos
_SEPARATOR_RE = re.compile(r"^[\s=\-─━═]{10,}$", re.MULTILINE)

# pip already satisfied
_PIP_SATISFIED_RE = re.compile(
    r"^Requirement already satisfied:.*$", re.MULTILINE
)

# npm/yarn install lines
_NPM_NOISE_RE = re.compile(
    r"^("
    r"added \d+ packages.*$"
    r"|npm warn.*$"
    r"|npm notice.*$"
    r")",
    re.MULTILINE,
)

# Linhas em branco repetidas (3+ → 1)
_BLANK_LINES_RE = re.compile(r"\n{3,}")


# ============================================
# CORE CLEANER
# ============================================

def clean_output(
    raw: str,
    max_lines: int = 150,
    max_chars: int = 8000,
    keep_errors: bool = True,
    context: Optional[str] = None,
) -> str:
    """
    Limpa output de CLI/Python para economizar tokens.

    Args:
        raw: Output bruto do comando
        max_lines: Máximo de linhas no resultado
        max_chars: Máximo de caracteres no resultado
        keep_errors: Priorizar linhas de erro (stderr, traceback)
        context: Tipo de comando ("test", "build", "install", "general")

    Returns:
        Output limpo e compactado
    """
    if not raw or not raw.strip():
        return "(sem output)"

    text = raw

    # 1. Remover ANSI escape codes
    text = _ANSI_RE.sub("", text)

    # 2. Remover progress bars e spinners
    text = _PROGRESS_RE.sub("", text)

    # 3. Remover pip "already satisfied"
    text = _PIP_SATISFIED_RE.sub("", text)

    # 4. Remover npm noise
    text = _NPM_NOISE_RE.sub("", text)

    # 5. Comprimir separadores decorativos
    text = _SEPARATOR_RE.sub("---", text)

    # 6. Detectar contexto automaticamente se não fornecido
    if context is None:
        context = _detect_context(text)

    # 7. Filtros específicos por contexto
    if context == "test":
        text = _clean_test_output(text)
    elif context == "install":
        text = _clean_install_output(text)

    # 8. Remover linhas em branco repetidas
    text = _BLANK_LINES_RE.sub("\n\n", text)

    # 9. Limpar cada linha (strip + dedup consecutivos)
    lines = text.split("\n")
    cleaned_lines: list[str] = []
    prev_line = ""
    dup_count = 0
    for line in lines:
        stripped = line.rstrip()
        if stripped == prev_line and stripped:
            dup_count += 1
            if dup_count == 1:
                cleaned_lines.append(f"  ... (linhas repetidas omitidas)")
            continue
        else:
            dup_count = 0
        prev_line = stripped
        cleaned_lines.append(stripped)

    # 10. Truncar inteligente: cabeça + cauda
    if len(cleaned_lines) > max_lines:
        head_size = max_lines // 3
        tail_size = max_lines - head_size - 1
        omitted = len(cleaned_lines) - head_size - tail_size
        cleaned_lines = (
            cleaned_lines[:head_size]
            + [f"\n... [{omitted} linhas omitidas] ...\n"]
            + cleaned_lines[-tail_size:]
        )

    result = "\n".join(cleaned_lines).strip()

    # 11. Truncar por chars
    if len(result) > max_chars:
        half = max_chars // 2
        result = (
            result[:half]
            + f"\n\n... [{len(result) - max_chars} chars omitidos] ...\n\n"
            + result[-half:]
        )

    return result


# ============================================
# CONTEXT-SPECIFIC CLEANERS
# ============================================

def _detect_context(text: str) -> str:
    """Auto-detecta o tipo de output."""
    text_lower = text[:2000].lower()
    if any(kw in text_lower for kw in ["passed", "failed", "error", "test_", "pytest", "unittest"]):
        return "test"
    if any(kw in text_lower for kw in ["installing", "collecting", "pip install", "npm install"]):
        return "install"
    if any(kw in text_lower for kw in ["building", "compiling", "webpack", "vite", "tsc"]):
        return "build"
    return "general"


def _clean_test_output(text: str) -> str:
    """Para testes: remove linhas de PASSED, mantém apenas FAILED/ERROR."""
    lines = text.split("\n")
    result: list[str] = []
    pass_count = 0
    in_traceback = False

    for line in lines:
        # Manter tracebacks integrais
        if "Traceback" in line or "Error:" in line or "FAILED" in line:
            in_traceback = True
        if in_traceback:
            result.append(line)
            if line.strip() == "" and in_traceback:
                in_traceback = False
            continue

        # Contar passes
        if _TEST_PASS_RE.match(line):
            pass_count += 1
            continue

        result.append(line)

    if pass_count > 0:
        result.insert(0, f"[{pass_count} testes passaram — output omitido]")

    return "\n".join(result)


def _clean_install_output(text: str) -> str:
    """Para instalações: remove noise de progresso, mantém resultado final."""
    text = _PIP_SATISFIED_RE.sub("", text)
    lines = text.split("\n")
    important: list[str] = []
    skipped = 0

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        # Manter linhas importantes
        if any(kw in stripped.lower() for kw in [
            "successfully", "error", "failed", "warning",
            "installed", "already", "not found", "version"
        ]):
            important.append(stripped)
        else:
            skipped += 1

    if skipped > 0:
        important.append(f"[{skipped} linhas de progresso omitidas]")

    return "\n".join(important)


# ============================================
# STATS (para métricas)
# ============================================

def compression_stats(original: str, cleaned: str) -> dict:
    """Retorna estatísticas de compressão."""
    orig_chars = len(original)
    clean_chars = len(cleaned)
    orig_lines = original.count("\n") + 1
    clean_lines = cleaned.count("\n") + 1
    savings_pct = round((1 - clean_chars / max(orig_chars, 1)) * 100, 1)

    return {
        "original_chars": orig_chars,
        "cleaned_chars": clean_chars,
        "original_lines": orig_lines,
        "cleaned_lines": clean_lines,
        "savings_pct": savings_pct,
        "tokens_saved_estimate": (orig_chars - clean_chars) // 4,
    }
