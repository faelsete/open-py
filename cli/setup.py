#!/usr/bin/env python3
"""
Open-PY Setup Wizard — Reconfiguração interativa
Roda via: openpy setup
"""

import os
import sys

INSTALL_DIR = os.environ.get("OPENPY_DIR", "/opt/open-py")
sys.path.insert(0, INSTALL_DIR)

# Cores
R = "\033[0m"
B = "\033[1m"
D = "\033[2m"
C = "\033[36m"
G = "\033[32m"
Y = "\033[33m"
RED = "\033[31m"
M = "\033[35m"


def input_default(prompt: str, default: str = "") -> str:
    """Input com valor default"""
    if default:
        val = input(f"  {prompt} [{D}{default}{R}]: ").strip()
        return val if val else default
    return input(f"  {prompt}: ").strip()


def yn(prompt: str, default: bool = True) -> bool:
    """Pergunta sim/não"""
    hint = "S/n" if default else "s/N"
    val = input(f"  {prompt} [{hint}]: ").strip().lower()
    if not val:
        return default
    return val in ("s", "sim", "y", "yes")


def show_current(config) -> None:
    """Mostra configuração atual"""
    print(f"\n  {B}═══ CONFIGURAÇÃO ATUAL ═══{R}\n")

    # Core
    print(f"  {B}Core:{R}")
    print(f"    Nome: {config.core.name}")
    print(f"    Versão: {config.core.version}")
    print(f"    Idioma: {config.core.language}")
    print()

    # Telegram
    print(f"  {B}Telegram:{R}")
    if config.telegram.bot_token:
        token_short = config.telegram.bot_token[:8] + "..." + config.telegram.bot_token[-4:]
        print(f"    Bot Token: {token_short}")
        print(f"    Usuários: {config.telegram.allowed_users}")
    else:
        print(f"    {D}(não configurado){R}")
    print()

    # Provedores
    print(f"  {B}Provedores LLM:{R}")
    provs = get_providers(config)
    for name, p in provs.items():
        if p.enabled and p.api_key:
            key_short = p.api_key[:8] + "..." + p.api_key[-4:]
            model = p.model or "(default)"
            print(f"    {G}✅ {name}{R}: {model} ({key_short})")
        else:
            print(f"    {D}⬚  {name}: desabilitado{R}")
    print()


def get_providers(config) -> dict:
    return {
        "openai": config.providers.openai,
        "anthropic": config.providers.anthropic,
        "openrouter": config.providers.openrouter,
        "nvidia": config.providers.nvidia,
        "opencode": config.providers.opencode,
    }


def menu_principal(config) -> str:
    """Menu principal"""
    print(f"""
  {B}O que deseja fazer?{R}

  {C}1{R} — Configurar Telegram (token, usuários)
  {C}2{R} — Gerenciar Provedores LLM
  {C}3{R} — Alterar modelo padrão
  {C}4{R} — Ver configuração atual
  {C}5{R} — Resetar configuração (volta ao padrão)
  {C}0{R} — Sair e salvar
""")
    return input(f"  {B}Opção:{R} ").strip()


def setup_telegram(config) -> None:
    """Configura Telegram"""
    print(f"\n  {B}═══ TELEGRAM ═══{R}\n")

    token = input_default("Bot Token (@BotFather)", config.telegram.bot_token or "")
    if token:
        config.telegram.bot_token = token

    users_str = input_default(
        "User IDs autorizados (separados por vírgula)",
        ",".join(str(u) for u in config.telegram.allowed_users) if config.telegram.allowed_users else ""
    )
    if users_str:
        try:
            config.telegram.allowed_users = [int(u.strip()) for u in users_str.split(",") if u.strip()]
            print(f"  {G}✅ {len(config.telegram.allowed_users)} usuários configurados{R}")
        except ValueError:
            print(f"  {RED}❌ IDs inválidos — mantendo anterior{R}")

    print(f"  {G}✅ Telegram configurado{R}")


def setup_providers(config) -> None:
    """Gerencia provedores"""
    provs = get_providers(config)

    while True:
        print(f"\n  {B}═══ PROVEDORES LLM ═══{R}\n")

        # Listar
        idx = 1
        prov_list = []
        for name, p in provs.items():
            if p.enabled and p.api_key:
                model = p.model or "(default)"
                print(f"  {G}{idx}{R} — {G}✅ {name}{R}: {model}")
            else:
                print(f"  {D}{idx}{R} — {D}⬚  {name}: desabilitado{R}")
            prov_list.append(name)
            idx += 1

        print(f"""
  {B}Ações:{R}
  {C}a{R} — Ativar/configurar provedor
  {C}d{R} — Desativar provedor
  {C}m{R} — Trocar modelo de um provedor
  {C}v{R} — Voltar
""")
        action = input(f"  {B}Ação:{R} ").strip().lower()

        if action == "v" or action == "":
            break

        elif action == "a":
            print(f"\n  Provedores disponíveis: {', '.join(prov_list)}")
            name = input(f"  Nome do provedor: ").strip().lower()
            if name not in provs:
                print(f"  {RED}❌ Provedor inválido{R}")
                continue

            p = provs[name]
            key = input_default("API Key", p.api_key or "")
            if not key:
                print(f"  {RED}❌ API Key é obrigatória{R}")
                continue

            p.api_key = key
            p.enabled = True

            # API base para provedores custom
            if name == "openrouter":
                p.api_base = p.api_base or "https://openrouter.ai/api/v1"
            elif name == "opencode":
                base = input_default("API Base URL", p.api_base or "")
                if base:
                    p.api_base = base

            # Modelo
            model = input_default("Modelo", p.model or "")
            if model:
                p.model = model

            print(f"  {G}✅ {name} ativado{R}")

        elif action == "d":
            name = input(f"  Desativar qual provedor? ").strip().lower()
            if name in provs:
                provs[name].enabled = False
                print(f"  {G}✅ {name} desativado{R}")
            else:
                print(f"  {RED}❌ Provedor não encontrado{R}")

        elif action == "m":
            name = input(f"  Qual provedor? ").strip().lower()
            if name in provs and provs[name].enabled:
                model = input_default("Novo modelo", provs[name].model or "")
                if model:
                    provs[name].model = model
                    print(f"  {G}✅ Modelo do {name} alterado para: {model}{R}")
            else:
                print(f"  {RED}❌ Provedor não encontrado ou desabilitado{R}")


def setup_model(config) -> None:
    """Altera modelo padrão"""
    print(f"\n  {B}═══ MODELO PADRÃO ═══{R}\n")
    print(f"  O modelo padrão é usado quando o provedor não tem modelo específico.\n")

    model = input_default("Modelo padrão", config.core.default_model or "")
    if model:
        config.core.default_model = model
        print(f"  {G}✅ Modelo padrão: {model}{R}")

    fallback = input_default("Modelo fallback", config.core.fallback_model or "")
    if fallback:
        config.core.fallback_model = fallback
        print(f"  {G}✅ Fallback: {fallback}{R}")


def reset_config(config) -> None:
    """Reseta configuração"""
    print(f"\n  {Y}⚠️  Isso vai resetar TODAS as configurações para o padrão!{R}")
    if yn("Tem certeza?", False):
        from shared.config import OpenPYConfig
        new = OpenPYConfig()
        # Manter install_dir
        new.core.install_dir = config.core.install_dir
        # Copiar db password (precisa pra conectar)
        new.database.password = config.database.password
        config.__dict__.update(new.__dict__)
        print(f"  {G}✅ Configuração resetada{R}")
    else:
        print(f"  {D}Cancelado{R}")


def main() -> None:
    from shared.config import load_config, save_config

    # Forçar reload
    import shared.config as cfg_mod
    cfg_mod._config = None
    config = load_config()

    print(f"\n  {C}{B}🔧 Open-PY Setup Wizard{R}")
    print(f"  {D}Reconfigure sem precisar reinstalar{R}")

    while True:
        choice = menu_principal(config)

        if choice == "1":
            setup_telegram(config)
        elif choice == "2":
            setup_providers(config)
        elif choice == "3":
            setup_model(config)
        elif choice == "4":
            show_current(config)
        elif choice == "5":
            reset_config(config)
        elif choice in ("0", "q", ""):
            # Salvar
            save_config(config)
            print(f"\n  {G}✅ Configuração salva em openpy.toml{R}")
            if yn("Reiniciar o serviço agora?"):
                os.system("systemctl restart open-py")
                print(f"  {G}✅ Serviço reiniciado{R}")
            print()
            break
        else:
            print(f"  {RED}Opção inválida{R}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n  {Y}Cancelado{R}\n")
    except Exception as e:
        print(f"\n  {RED}❌ Erro: {e}{R}\n")
        sys.exit(1)
