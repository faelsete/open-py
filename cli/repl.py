#!/usr/bin/env python3
"""
Open-PY CLI REPL — Chat interativo no terminal (estilo Claude Code)
Usa o mesmo pipeline Lifecycle/Cortex do Telegram.
"""

import asyncio
import os
import sys
import signal
import readline

# Garante que o diretório raiz do projeto está no path
INSTALL_DIR = os.environ.get("OPENPY_DIR", "/opt/open-py")
sys.path.insert(0, INSTALL_DIR)

# ============================================
# CORES ANSI
# ============================================
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
MAGENTA = "\033[35m"
BLUE = "\033[34m"


def print_banner(config) -> None:
    """Exibe banner de boas-vindas"""
    version = config.core.version
    # Detectar provedor e modelo ativos
    provs = {
        "openai": config.providers.openai,
        "anthropic": config.providers.anthropic,
        "openrouter": config.providers.openrouter,
        "nvidia": config.providers.nvidia,
        "opencode": config.providers.opencode,
    }
    active_prov = "nenhum"
    active_model = "nenhum"
    for name, p in provs.items():
        if p.enabled and p.api_key:
            active_prov = name
            active_model = p.model or "(default)"
            break

    print(f"""
  {CYAN}{BOLD}🧠 Open-PY v{version} — Modo Terminal{RESET}
  {DIM}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{RESET}
  {DIM}Provedor:{RESET} {GREEN}{active_prov}{RESET} {DIM}|{RESET} {DIM}Modelo:{RESET} {GREEN}{active_model}{RESET}

  {DIM}Comandos: /model, /provider, /memory, /tools, /clear, /help, /exit{RESET}
""")


def handle_slash_command(cmd: str, config) -> bool:
    """
    Processa comandos com /. Retorna True se consumiu o input.
    """
    parts = cmd.strip().split(maxsplit=2)
    command = parts[0].lower()

    if command in ("/exit", "/quit", "/q"):
        print(f"\n  {YELLOW}👋 Até mais!{RESET}\n")
        sys.exit(0)

    elif command == "/help":
        print(f"""
  {BOLD}Comandos disponíveis:{RESET}

  {CYAN}/model{RESET}                Ver modelo atual
  {CYAN}/model set <nome>{RESET}    Trocar modelo
  {CYAN}/provider{RESET}            Ver provedor atual
  {CYAN}/memory{RESET}              Ver core memory (soul/essence)
  {CYAN}/tools{RESET}               Listar ferramentas disponíveis
  {CYAN}/clear{RESET}               Limpar histórico da sessão
  {CYAN}/tokens{RESET}              Tokens usados na sessão
  {CYAN}/help{RESET}                Esta mensagem
  {CYAN}/exit{RESET}                Sair
""")
        return True

    elif command == "/model":
        provs = {
            "openai": config.providers.openai,
            "anthropic": config.providers.anthropic,
            "openrouter": config.providers.openrouter,
            "nvidia": config.providers.nvidia,
            "opencode": config.providers.opencode,
        }
        if len(parts) >= 3 and parts[1] == "set":
            new_model = parts[2]
            for name, p in provs.items():
                if p.enabled and p.api_key:
                    p.model = new_model
                    from shared.config import save_config
                    save_config(config)
                    print(f"  {GREEN}✅ Modelo do {name} alterado para: {new_model}{RESET}")
                    print(f"  {YELLOW}⚠️  Reinicie o serviço Telegram: openpy restart{RESET}")
                    break
        else:
            for name, p in provs.items():
                if p.enabled and p.api_key:
                    model = p.model or "(default)"
                    print(f"  {GREEN}✅ {name}{RESET}: {model}")
        return True

    elif command == "/provider":
        provs = {
            "openai": config.providers.openai,
            "anthropic": config.providers.anthropic,
            "openrouter": config.providers.openrouter,
            "nvidia": config.providers.nvidia,
            "opencode": config.providers.opencode,
        }
        for name, p in provs.items():
            if p.enabled and p.api_key:
                key_short = p.api_key[:8] + "..." + p.api_key[-4:]
                model = p.model or "(default)"
                print(f"  {GREEN}✅ {name}{RESET}: {model} ({key_short})")
            else:
                print(f"  {DIM}⬚  {name}: desabilitado{RESET}")
        return True

    elif command == "/memory":
        soul_path = os.path.join(INSTALL_DIR, "data", "soul.md")
        essence_path = os.path.join(INSTALL_DIR, "data", "essence.md")
        print(f"\n  {BOLD}📝 Soul:{RESET}")
        if os.path.exists(soul_path):
            with open(soul_path) as f:
                for line in f:
                    print(f"  {DIM}{line.rstrip()}{RESET}")
        else:
            print(f"  {DIM}(vazio){RESET}")
        print(f"\n  {BOLD}🎭 Essence:{RESET}")
        if os.path.exists(essence_path):
            with open(essence_path) as f:
                for line in f:
                    print(f"  {DIM}{line.rstrip()}{RESET}")
        else:
            print(f"  {DIM}(vazio){RESET}")
        print()
        return True

    elif command == "/tools":
        try:
            from shared.config import load_config as _lc
            from tools.registry import ToolRegistry
            c = _lc()
            registry = ToolRegistry(c)
            tools = registry.list_tools()
            print(f"\n  {BOLD}🔧 {len(tools)} ferramentas:{RESET}\n")
            for t in tools:
                desc = t.get("description", "")[:60]
                print(f"  {CYAN}{t['name']}{RESET}  {DIM}{desc}{RESET}")
            print()
        except Exception as e:
            print(f"  {RED}❌ Erro ao listar tools: {e}{RESET}")
        return True

    elif command == "/clear":
        print(f"  {GREEN}✅ Histórico da sessão limpo{RESET}")
        return "clear"  # Signal to clear conversation

    elif command == "/tokens":
        return "tokens"  # Signal to show token count

    return False


async def run_repl() -> None:
    """Loop principal do REPL"""
    from shared.config import load_config
    config = load_config()
    print_banner(config)

    # Inicializar core (mesmo pipeline do Telegram)
    from core.lifecycle import OpenPY
    core = OpenPY()
    print(f"  {DIM}⏳ Carregando core...{RESET}", end="", flush=True)
    await core.startup()
    print(f"\r  {GREEN}✅ Core pronto{RESET}          ")

    # Histórico readline
    history_file = os.path.join(INSTALL_DIR, "data", ".repl_history")
    try:
        readline.read_history_file(history_file)
    except FileNotFoundError:
        pass
    readline.set_history_length(500)

    session_tokens = {"prompt": 0, "completion": 0, "total": 0}
    user_id = 0  # CLI user

    while True:
        try:
            user_input = input(f"  {BOLD}{GREEN}>{RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n\n  {YELLOW}👋 Até mais!{RESET}\n")
            break

        if not user_input:
            continue

        # Salvar histórico
        try:
            readline.write_history_file(history_file)
        except Exception:
            pass

        # Slash commands
        if user_input.startswith("/"):
            result = handle_slash_command(user_input, config)
            if result == "clear":
                # Limpar histórico conversacional
                core._conversation_histories.clear()
                continue
            elif result == "tokens":
                print(f"\n  {BOLD}📊 Tokens da sessão:{RESET}")
                print(f"  Prompt:     {session_tokens['prompt']}")
                print(f"  Completion: {session_tokens['completion']}")
                print(f"  Total:      {session_tokens['total']}")
                print()
                continue
            elif result:
                continue

        # Processar via Cortex
        print(f"\n  {DIM}🧠 Pensando...{RESET}", end="", flush=True)
        response_text = ""
        first_chunk = True

        try:
            async for event in core.process(
                input_text=user_input,
                input_type="text",
                user_id=user_id,
            ):
                etype = event.get("type", "")

                if etype == "status":
                    status = event.get("content", "")
                    if status:
                        # Limpar "Pensando..." e mostrar status
                        print(f"\r  {DIM}⚙️  {status}{RESET}          ", flush=True)

                elif etype == "final":
                    content = event.get("content", "") or event.get("response", "")
                    if first_chunk:
                        # Limpar "Pensando..."
                        print(f"\r{'':60}\r", end="", flush=True)
                        first_chunk = False

                    if content:
                        response_text = content
                        # Formatar resposta
                        print(f"  {CYAN}{BOLD}🧠{RESET} ", end="")
                        # Imprimir com indentação
                        lines = content.split("\n")
                        print(lines[0])
                        for line in lines[1:]:
                            print(f"     {line}")
                    else:
                        print(f"\r  {RED}⚠️ Sem resposta do modelo{RESET}")

                elif etype == "error":
                    msg = event.get("content", "") or event.get("message", "Erro desconhecido")
                    print(f"\r  {RED}❌ {msg}{RESET}")

        except Exception as e:
            print(f"\r  {RED}❌ Erro: {e}{RESET}")

        print()  # Linha em branco após resposta

    # Cleanup
    try:
        readline.write_history_file(history_file)
    except Exception:
        pass


def main() -> None:
    """Entrypoint"""
    # Ignorar SIGINT gracefully
    signal.signal(signal.SIGINT, lambda *_: None)

    try:
        asyncio.run(run_repl())
    except KeyboardInterrupt:
        print(f"\n  {YELLOW}👋 Até mais!{RESET}\n")
    except Exception as e:
        print(f"\n  {RED}❌ Erro fatal: {e}{RESET}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
