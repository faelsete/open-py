# 🧠 Open-PY — Framework de Agentes Autônomos

<p align="center">
  <img src="assets/logo.png" alt="Open-PY Logo" width="200">
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-AGPL%20v3-blue.svg" alt="License: AGPL-3.0"></a>
  <img src="https://img.shields.io/badge/version-3.1.0-green.svg" alt="Version">
  <img src="https://img.shields.io/badge/python-3.10%2B-blue.svg" alt="Python">
  <img src="https://img.shields.io/badge/platform-Ubuntu%2022.04%2B-orange.svg" alt="Platform">
  <img src="https://img.shields.io/badge/PostgreSQL-16%2B-336791.svg" alt="PostgreSQL">
</p>

<p align="center">
  <b>Framework 100% Python para criação e orquestração de agentes autônomos inteligentes</b><br>
  <i>Roda nativamente em Linux • Telegram como frontend • PostgreSQL como memória de longo prazo</i>
</p>

<p align="center">

```bash
curl -fsSL https://raw.githubusercontent.com/faelsete/open-py/main/install.sh | sudo bash
```

</p>

---

## 📖 Índice

- [Visão Geral](#-visão-geral)
- [Arquitetura](#-arquitetura)
- [Pré-requisitos](#-pré-requisitos)
- [Instalação](#-instalação)
- [Configuração](#️-configuração)
- [Uso](#-uso)
- [Agentes](#-agentes)
- [Sistema de Memória](#-sistema-de-memória)
- [Ferramentas Builtin](#-ferramentas-builtin)
- [Identidade (Soul e Essence)](#-identidade-soul-e-essence)
- [CLI do Terminal](#-cli-do-terminal)
- [Diagnóstico e Auto-Reparo](#-diagnóstico-e-auto-reparo)
- [Estrutura de Diretórios](#-estrutura-de-diretórios)
- [Segurança](#-segurança)
- [Troubleshooting](#-troubleshooting)
- [API de Referência](#-api-de-referência)
- [Changelog](#-changelog)
- [Licença](#-licença)

---

## 🔭 Visão Geral

Open-PY é um framework autônomo que orquestra múltiplos agentes de IA especializados sob um **Core Brain** central. O Core nunca executa tarefas diretamente — ele **pensa** em 4 camadas e **delega** para o agente mais adequado.

### Características principais

| Feature | Descrição |
|---------|-----------|
| 🧠 **Thinking Engine** | Motor de raciocínio em 4 camadas (Captura → Roteamento → Execução → Resposta) |
| 🤖 **6 Agentes Builtin** | vision, builder, cleaner, researcher, transcriber, agent_creator |
| 💾 **Memória Semântica** | Busca contextual (pgvector): só lembra o relevante, como um cérebro humano |
| 📦 **Message Batching** | Agrupa mensagens em janela de 2s antes de processar — nunca responde fragmentado |
| 📋 **Task Queue** | Fila obrigatória com prioridade (CRITICAL > HIGH > NORMAL > LOW) |
| 🛡️ **Rate Limiter** | Token bucket: 1 msg/s per-chat, 20 msg/s global, deduplicação |
| 📝 **Audit Log Imutável** | Chain SHA-256 (blockchain-style), append-only, verificação de integridade |
| 🧠 **Auto-Learning** | Salva TUDO automaticamente, extrai e lembra preferências do usuário |
| 🔐 **SYSTEM_SECURITY** | Bloco de segurança injetado em toda delegação — nunca truncado |
| 🔄 **Multi-Provedor LLM** | OpenAI, Anthropic, OpenRouter, NVIDIA NIM, Custom (com fallback automático) |
| 🩺 **Auto-Diagnóstico** | 14 checks de saúde + reparo automático via `/doctor` |
| ⏰ **Scheduler** | Heartbeat, migração diária de memórias, cron jobs |
| 🧬 **Identidade Persistente** | soul.md (memória inalterável) + essence.md (personalidade) com versionamento SHA-256 |

---

## 🏗 Arquitetura

```
     ┌─────────────────────────────────────────────────────┐
     │                    TELEGRAM                          │
     │              (Frontend Único)                        │
     │     Texto • Imagem • Áudio • Vídeo • Documento      │
     └────────────────────┬────────────────────────────────┘
                          │
                          ▼
     ┌─────────────────────────────────────────────────────┐
     │                   CORE BRAIN                         │
     │  ┌──────────────────────────────────────────────┐   │
     │  │ Camada 1: CAPTURA — Classifica input          │   │
     │  │ Camada 2: ROTEAMENTO — Decide quem resolve    │   │
     │  │ Camada 3: PREPARAÇÃO — Monta task + contexto  │   │
     │  │ Camada 4: RESPOSTA — Formata e entrega        │   │
     │  └──────────────────────────────────────────────┘   │
     │  + soul.md (memória permanente)                      │
     │  + essence.md (personalidade)                        │
     └───────┬───────┬───────┬───────┬───────┬─────────────┘
             │       │       │       │       │
             ▼       ▼       ▼       ▼       ▼
     ┌───────┐ ┌────────┐ ┌───────┐ ┌──────────┐ ┌───────────┐
     │vision │ │builder │ │cleaner│ │researcher│ │transcriber│
     │       │ │        │ │       │ │          │ │           │
     │imagens│ │código  │ │limpeza│ │pesquisa  │ │áudio→texto│
     └───────┘ └────────┘ └───────┘ └──────────┘ └───────────┘
          │         │         │          │             │
          └─────────┴─────────┴──────────┴─────────────┘
                              │
                              ▼
     ┌─────────────────────────────────────────────────────┐
     │                   MEMÓRIA                            │
     │                                                      │
     │  Contexto (RAM)  →  memory.md  →  PostgreSQL         │
     │   buffer volátil    a cada 1h     migração 00:00     │
     │                     ou 128K       .md descartados     │
     │                                                      │
     │  + pgvector (busca semântica vetorial)                │
     │  + pg_trgm  (busca por texto fuzzy)                  │
     └─────────────────────────────────────────────────────┘
```

### Fluxo de um pedido

```
1. Usuário envia mensagem(s) no Telegram
2. Rate limiter verifica flood + deduplicação
3. Batcher coleta mensagens (janela de 2s)
4. Se recebeu 5 msgs → une em 1 input: "Leia TODAS antes de responder"
5. Core classifica o tipo (text/image/audio/video/code/command)
6. Core avalia urgência (critical/high/normal/low)
7. Memória semântica: busca APENAS memórias relevantes ao input atual
   (perguntou sobre Python? → só lembra de programação, não de culinária)
8. Core decide: responder direto OU delegar para agente
9. Se delegado → SYSTEM_SECURITY injetado + agente executa
10. Resultado volta ao Core → formata → envia ao Telegram
11. Auto-learner salva interação + extrai preferências
12. Audit log registra ações críticas com hash SHA-256
```

---

## 📋 Pré-requisitos

### Hardware mínimo

| Recurso | Mínimo | Recomendado |
|---------|--------|-------------|
| **RAM** | 1 GB | 2 GB+ |
| **Disco** | 5 GB | 10 GB+ |
| **CPU** | 1 vCPU | 2 vCPU+ |
| **Rede** | Necessário | — |

### Software necessário

| Software | Versão | Instalado automaticamente? |
|----------|--------|---------------------------|
| **Linux** | Ubuntu 22.04+ / Debian 12+ | ❌ (pré-requisito) |
| **Python** | 3.10+ | ✅ Sim |
| **PostgreSQL** | 14+ | ✅ Sim |
| **pgvector** | 0.5+ | ✅ Sim |
| **Bubblewrap** | 0.8+ | ✅ Sim |
| **FFmpeg** | 5.0+ | ✅ Sim |
| **curl, jq, git** | — | ✅ Sim |

### Credenciais necessárias (tenha antes de instalar)

1. **Chave API de LLM** (pelo menos uma):
   | Provedor | Onde obter | Custo |
   |----------|-----------|-------|
   | OpenAI | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) | Pago |
   | Anthropic | [console.anthropic.com](https://console.anthropic.com/settings/keys) | Pago |
   | OpenRouter ⭐ | [openrouter.ai/keys](https://openrouter.ai/keys) | Pay-per-use |
   | NVIDIA NIM | [build.nvidia.com](https://build.nvidia.com/) | Free tier |

2. **Token de Bot Telegram**:
   - Abra o Telegram → busque `@BotFather`
   - Envie `/newbot` → siga as instruções → copie o token

3. **Seu Telegram User ID**:
   - Envie `/start` para `@userinfobot` → copie o número

---

## 🚀 Instalação

### Método 1: One-liner (Recomendado)

```bash
curl -fsSL https://raw.githubusercontent.com/faelsete/open-py/main/install.sh | sudo bash
```

### Método 2: Git Clone Manual

```bash
git clone https://github.com/faelsete/open-py.git /tmp/open-py
cd /tmp/open-py
chmod +x install.sh
sudo bash install.sh
```

### Atualização

```bash
openpy update
```

### ☢️ Limpeza Nuclear (Nuclear Reset)

Se você precisar **apagar TUDO** (memórias, banco de dados, identidades e configurações) e começar do zero, use um dos comandos abaixo:

**Via Terminal (Recomendado):**

```bash
openpy nuke
```

O sistema pedirá **duas confirmações**: primeiro digite `NUKE`, depois `SIM`.

**Via One-liner (Fora do sistema):**

```bash
curl -fsSL https://raw.githubusercontent.com/faelsete/open-py/main/nuke.sh | sudo bash
```

> [!CAUTION]
> Isso irá destruir permanentemente: Banco de dados, memórias, `soul.md`, `essence.md` e `openpy.toml`. Use com cuidado!

### O que o instalador faz (8 etapas automáticas)

```
[1/8] Dependências do Sistema
     → Instala python3, postgresql, bwrap, ffmpeg, git
     → Instala pgvector (apt → PGDG repo → compilação)

[2/8] Baixando Open-PY
     → Clona repositório em /opt/open-py
     → Cria 11 diretórios de dados

[3/8] PostgreSQL
     → Cria user openpy, database openpy, extensões pgvector + pg_trgm
     → Gera senha segura automaticamente

[4/8] Ambiente Python
     → Cria venv isolado, instala 100+ dependências

[5/8] Provedores LLM (menu interativo)
     → Pergunta quais provedores usar (1-5)
     → Pede API key + Base URL de cada um
     → URLs padrão pré-configuradas (NVIDIA, OpenAI, etc.)

[6/8] Telegram Bot (menu interativo)
     → Pede token do bot + seu User ID
     → Valida o token automaticamente via API

[7/8] Configuração
     → Gera openpy.toml com todas configurações
     → Executa migrations do banco (6 tabelas)

[8/8] Serviço e CLI
     → Cria serviço systemd (auto-start)
     → Instala comando `openpy` global
```

---

## ⚙️ Configuração

### Arquivo principal: `/opt/open-py/openpy.toml`

```toml
[core]
name = "Open-PY"
version = "2.2.0"
language = "pt-BR"
default_model = "meta/llama-3.1-405b-instruct"  # Modelo padrão
fallback_model = ""                              # Modelo de fallback
max_concurrent_agents = 10                       # Máx agentes simultâneos
thinking_layers = 4                              # Camadas de raciocínio

[database]
host = "localhost"
port = 5432
name = "openpy"
user = "openpy"
password = "auto_gerada"                      # Gerada na instalação

[telegram]
bot_token = "123456:ABC..."                   # Token do BotFather
allowed_users = [123456789]                    # Seu Telegram User ID
max_message_length = 4096
polling_mode = true

[memory]
context_max_tokens = 128000                   # Salva ao atingir 128K
context_save_interval_minutes = 60            # Ou salva a cada 1h
migration_hour = 0                            # Migração diária às 00:00
migration_minute = 0
discard_md_after_migration = true             # Descarta .md após migrar
embedding_model = "all-MiniLM-L6-v2"         # Modelo de embeddings (local)
embedding_dimensions = 384
max_search_results = 10

[providers.openai]
api_key = ""
api_base = "https://api.openai.com/v1"        # URL pré-configurada
enabled = false

[providers.anthropic]
api_key = ""
api_base = "https://api.anthropic.com"        # URL pré-configurada
enabled = false

[providers.openrouter]
api_key = "sk-or-..."
api_base = "https://openrouter.ai/api/v1"     # URL pré-configurada
enabled = true

[providers.nvidia]
api_key = "nvapi-..."
api_base = "https://integrate.api.nvidia.com/v1"  # NÃO coloque /chat/completions
enabled = true

[providers.opencode]                          # Endpoint customizado
api_key = ""
api_base = ""
enabled = false

[scheduler]
heartbeat_interval_seconds = 60               # Health check a cada 60s
max_cron_jobs = 50

[doctor]
auto_repair = true                            # Reparo automático
snapshot_on_startup = true                    # Snapshot ao iniciar
```

Para editar: `openpy config`

---

## 🎮 Uso

### Comandos do Telegram

| Comando | Descrição | Exemplo |
|---------|-----------|---------|
| `/start` | Iniciar o bot | — |
| `/help` | Lista completa de comandos | — |
| `/status` | Status do sistema (RAM, disco, DB, LLM) | — |
| `/health` | Relatório completo de saúde (DB, LLM, Memória, Agentes) | — |
| `/memory` | Estatísticas de memória | — |
| `/agents` | Listar agentes ativos | — |
| `/tasks` | Tarefas em andamento | — |
| `/remember <texto>` | Salvar memória manualmente | `/remember Meu IP é 192.168.1.1` |
| `/recall <busca>` | Buscar nas memórias (semântica) | `/recall qual meu IP` |
| `/soul` | Ver memória permanente | — |
| `/essence` | Ver personalidade atual | — |
| `/audit` | Verificar integridade do audit log | — |

### Mensagens livres

Envie qualquer conteúdo — o Core classifica e roteia automaticamente:

| Tipo | O que acontece | Agente |
|------|---------------|--------|
| 💬 Texto conversacional | Core responde direto | — |
| 🐍 Código / erro | Delega para builder | builder |
| 🖼️ Imagem | Delega para análise visual | vision |
| 🎵 Áudio | Delega para transcrição | transcriber |
| 🎬 Vídeo | Delega para análise | vision |
| 📄 Documento | Delega para leitura | transcriber |
| 🔍 Texto com "pesquisar" | Delega para pesquisa web | researcher |

---

## 🤖 Agentes

### Agentes Builtin (6)

| Agente | Função | Ferramentas | Rede | Shell | Filesystem |
|--------|--------|-------------|:----:|:-----:|:----------:|
| **vision** | Analisa imagens e vídeos | — | ❌ | ❌ | ❌ |
| **builder** | Código, debug, scripts | shell_exec, file_ops, http | ✅ | ✅ | ✅ |
| **cleaner** | Limpeza de arquivos/cache | file_ops (restrito) | ❌ | ❌ | ✅ |
| **researcher** | Pesquisa web profunda | web_search, http | ✅ | ❌ | ❌ |
| **transcriber** | Transcrição de áudio | file_ops, ffmpeg | ❌ | ❌ | ✅ |
| **agent_creator** | Cria novos agentes dinâmicos | — | ❌ | ❌ | ❌ |

### Criando agentes customizados

Via Telegram, peça ao Core:
```
Crie um agente chamado "tradutor" que traduz textos entre pt-BR e en-US.
Ele deve ter acesso à rede para usar APIs de tradução.
```

O `agent_creator` vai gerar o agente com as permissões solicitadas.

---

## 💾 Sistema de Memória

### 3 Camadas

```
┌──────────────────────────────────────────────────────────────┐
│ CAMADA 1: CONTEXTO (RAM)                                     │
│ • Buffer volátil em memória                                   │
│ • Armazena interações recentes                                │
│ • Salva automaticamente quando:                               │
│   - Atinge 128K tokens                                        │
│   - A cada 60 minutos                                         │
├──────────────────────────────────────────────────────────────┤
│ CAMADA 2: MEMORY.MD (Filesystem)                              │
│ • Arquivos .md diários em /opt/open-py/data/memory/daily/     │
│ • Vários arquivos por dia (timestamps no nome)                │
│ • Formato: markdown com user/assistant alternados             │
├──────────────────────────────────────────────────────────────┤
│ CAMADA 3: POSTGRESQL (Longo Prazo)                            │
│ • Migração automática diária às 00:00                         │
│ • .md descartados após migração bem-sucedida                  │
│ • Busca semântica via pgvector (embeddings)                   │
│ • Busca fuzzy via pg_trgm                                     │
│ • Busca por tags automáticas                                  │
│ • Busca por data/período                                      │
└──────────────────────────────────────────────────────────────┘
```

### Busca Semântica Contextual (como um cérebro humano)

O Open-PY **não carrega 1M de tokens** a cada pergunta. Ele funciona como um cérebro humano:

```
Pergunta: "Como instalar o Django?"
 → Busca semântica retorna: memórias sobre Python, pip, projetos web
 → NÃO retorna: memórias sobre culinária, carros, ou amor

Pergunta: "Qual era aquele servidor que configuramos?"
 → Busca: memórias com IPs, servidores, config
 → NÃO retorna: memórias sobre código Python
```

**Budget**: máximo ~2000 tokens (≈8000 chars) injetados por consulta.

### Auto-Learning

O sistema aprende automaticamente a cada interação:

| O que detecta | Como salva | Importância |
|---------------|-----------|:-----------:|
| "Prefiro usar TypeScript" | Tag: preferência/positive | ⭐⭐⭐⭐ (8) |
| "Nunca use var em JS" | Tag: preferência/negative | ⭐⭐⭐⭐ (8) |
| "Perfeito, é isso!" | Tag: feedback/positive | ⭐⭐⭐ (7) |
| "Tá errado, refaça" | Tag: feedback/negative | ⭐⭐⭐ (7) |
| Resumo de sessão | Tag: resumo/auto-aprendido | ⭐⭐ (4) |

### Tags automáticas

O sistema extrai tags automaticamente baseado em palavras-chave:
- `python`, `javascript`, `api`, `database`, `docker`, `git`, `linux`, `nginx`, etc.

---

## 📦 Message Batching & Task Queue

### Message Batching

Se você enviar 10 mensagens seguidas, o bot **NÃO** responde 10 vezes. Ele:

1. Coleta todas as mensagens em uma janela de 2 segundos
2. Concatena em um input único: `[Mensagem 1]: ... [Mensagem 2]: ...`
3. Adiciona header: "O usuário enviou N mensagens. Leia TODAS antes de responder"
4. Processa uma vez só → resposta unificada e coerente

### Task Queue (Fila Obrigatória)

Toda tarefa entra em uma fila com prioridade:

| Prioridade | Quando | Exemplos |
|:----------:|--------|----------|
| 🔴 CRITICAL | "urgente", "caiu", "fora do ar" | Servidor down, erro em produção |
| 🟡 HIGH | "rápido", "logo" | Bug report, deploy |
| 🟢 NORMAL | Padrão | Perguntas, tarefas |
| ⚪ LOW | Automações, background | Limpeza, backups |

---

## 🔧 Ferramentas Builtin

| Ferramenta | Categoria | Descrição |
|------------|-----------|-----------|
| `web_search` | network | Busca na web via DuckDuckGo (gratuito) |
| `read_file` | io | Lê conteúdo de arquivo |
| `write_file` | io | Escreve conteúdo em arquivo |
| `list_files` | io | Lista arquivos de diretório |
| `delete_file` | io | Deleta arquivo |
| `shell_exec` | system | Executa comando shell (com timeout) |
| `http_get` | network | Faz requests HTTP GET |

---

## 🧬 Identidade (Soul e Essence)

### `data/soul.md` — Memória Permanente

Informações que o Core **nunca deve esquecer**. Este arquivo é carregado no system prompt a cada inicialização.

```markdown
# Soul — Memória Permanente

## Meu Dono
- Nome: [Seu nome]
- Telegram ID: [Seu ID]

## Regras Invioláveis
- Nunca executar rm -rf /
- Sempre pedir confirmação antes de deletar dados

## Coisas que Aprendi
- O servidor está em 207.180.251.211
- O projeto principal usa Python + PostgreSQL
```

Editar: `openpy soul`

### `data/essence.md` — Personalidade

Define **como** o Core se expressa.

```markdown
# Essence — Personalidade

## Idioma
Responder sempre em pt-BR

## Tom
Profissional mas descontraído. Usar emojis com moderação.

## Formato
- Respostas concisas
- Código sempre com syntax highlighting
- Usar bullet points para listas
```

Editar: `openpy essence`

---

## 💻 CLI do Terminal

```bash
openpy start       # Iniciar framework
openpy stop        # Parar
openpy restart     # Reiniciar
openpy status      # Status do serviço systemd
openpy logs        # Logs em tempo real (Ctrl+C para sair)
openpy doctor      # Diagnóstico completo (14 checks + auto-reparo)
openpy config      # Editar openpy.toml no editor
openpy soul        # Editar memória permanente
openpy essence     # Editar personalidade
openpy version     # Ver versão
openpy tags        # 📌 Listar todas as versões disponíveis
openpy rollback    # 🔄 Voltar para versão anterior (ex: openpy rollback v2.2.0)
openpy update      # Atualizar via GitHub (git pull + pip install + restart)
openpy nuke        # ☢️  Reset nuclear (apaga DB, memórias, config, TUDO)
openpy uninstall   # Remover completamente (pede confirmação)
```

---

## 🩺 Diagnóstico e Auto-Reparo

O comando `openpy doctor` executa **14 verificações**:

| # | Check | Auto-reparável |
|---|-------|:--------------:|
| 1 | openpy.toml existe | ❌ |
| 2 | Diretórios necessários | ✅ |
| 3 | PostgreSQL acessível | ❌ |
| 4 | Tabelas do banco | ✅ |
| 5 | Extensões (pgvector, pg_trgm) | ✅ |
| 6 | Python venv | ❌ |
| 7 | Bubblewrap instalado | ❌ |
| 8 | FFmpeg instalado | ❌ |
| 9 | soul.md presente | ❌ |
| 10 | essence.md presente | ❌ |
| 11 | Espaço em disco (>100MB) | ❌ |
| 12 | RAM (<90% uso) | ❌ |
| 13 | Token Telegram configurado | ❌ |
| 14 | Socket dir existe | ✅ |

---

## 📁 Estrutura de Diretórios

```
/opt/open-py/
├── openpy.toml              # Configuração global (chmod 600)
├── requirements.txt          # Dependências Python
├── pyproject.toml            # Metadados do projeto
├── __main__.py               # Entry point (python3 -m __main__)
├── install.sh                # Instalador interativo
├── README.md                 # Este arquivo
│
├── core/                     # 🧠 Cérebro do sistema
│   ├── __init__.py
│   ├── brain.py              # Thinking Engine (4 camadas)
│   ├── orchestrator.py       # Delegação, fallback, healthcheck, quotas
│   ├── lifecycle.py          # Startup / Shutdown + memória semântica
│   ├── audit_log.py          # 📝 Log imutável com chain SHA-256
│   ├── rate_limiter.py       # 🛡️ Token bucket (per-chat + global)
│   ├── message_queue.py      # 📦 Message batcher + task queue
│   └── auto_learner.py       # 🧠 Auto-learning de preferências
│
├── memory/                   # 💾 Sistema de memória
│   ├── __init__.py
│   └── manager.py            # 3 camadas + migração + busca híbrida
│
├── agents/                   # 🤖 Sistema de agentes
│   ├── __init__.py
│   ├── base.py               # Classe base (AgentBase)
│   ├── registry.py           # Registry de agentes ativos
│   └── factory.py            # Fábrica + 6 agentes builtin
│
├── telegram_bot/             # 📱 Frontend Telegram
│   ├── __init__.py
│   └── bot.py                # Bot aiogram 3.x (10 comandos + mídias)
│
├── providers/                # 🔌 Provedores LLM
│   ├── __init__.py
│   └── router.py             # LiteLLM multi-provedor + fallback
│
├── tools/                    # 🔧 Ferramentas
│   ├── __init__.py
│   └── registry.py           # 7 ferramentas builtin
│
├── scheduler/                # ⏰ Automações
│   ├── __init__.py
│   └── manager.py            # Heartbeat + cron + migração
│
├── doctor/                   # 🩺 Auto-diagnóstico
│   ├── __init__.py
│   └── diagnostics.py        # 14 checks + auto-reparo
│
├── shared/                   # 📦 Código compartilhado
│   ├── __init__.py
│   ├── config.py             # Pydantic models + TOML loader
│   ├── logger.py             # structlog + Rich
│   ├── models.py             # 6 enums + 7 dataclasses
│   ├── exceptions.py         # 16 exceções customizadas
│   └── migrations.py         # Schema SQL (6 tabelas)
│
├── data/                     # 📂 Dados persistentes
│   ├── soul.md               # Memória permanente (NUNCA apagar)
│   ├── essence.md            # Personalidade configurável
│   ├── agents/               # Dados runtime dos agentes
│   ├── memory/daily/         # Memory.md temporários
│   ├── media/                # photo/ audio/ video/ document/
│   ├── tools/custom/         # Ferramentas customizadas
│   ├── backups/              # Backups automáticos
│   └── logs/                 # Logs locais
│
├── tests/                    # 🧪 Suite de testes (12 testes)
│   ├── b1.py ... b12.py      # Testes unitários por módulo
│   └── run_tests.sh          # Runner de testes
│
└── venv/                     # 🐍 Virtual environment (gerado)
```

---

## 🔐 Segurança

| Medida | Descrição |
|--------|-----------|
| **Telegram allowlist** | Apenas IDs em `allowed_users` podem usar o bot |
| **Rate Limiter** | Token bucket: 1 msg/s per-chat, 20 msg/s global, deduplicação em 1s |
| **SYSTEM_SECURITY Block** | Regras de segurança injetadas verbatim em toda delegação — NUNCA truncadas |
| **Audit Log Imutável** | Chain SHA-256: cada entrada referencia o hash da anterior (blockchain-style) |
| **Context Compression Segura** | Preserva início+fim do input, nunca corta regras de segurança |
| **Identity Versioning** | soul.md e essence.md versionados com SHA-256 — detecta adulteração |
| **Bubblewrap sandbox** | Agentes rodam isolados via Linux namespaces |
| **Permissões mínimas** | Cada agente tem apenas as ferramentas que precisa |
| **Config protegido** | `openpy.toml` tem permissão `600` (só root lê) |
| **Senha auto-gerada** | Senha do PostgreSQL gerada com `openssl rand` |
| **Shell timeout** | Comandos shell têm timeout de 30s por padrão |
| **Agent Quotas** | Máx 20 agentes, 5 criações/hora, 10 custom |
| **Fallback Routing** | Se agente falha, tenta próximo automaticamente |
| **Healthcheck** | Auto-desativação após 3 falhas, auto-recovery após 5min |

### Audit Log

```
/opt/open-py/data/audit/
├── audit_2026-04-03.jsonl    ← Append-only, um por dia
├── audit_2026-04-02.jsonl
└── ...
```

Cada entrada:
```json
{
  "ts": "2026-04-03T17:40:00Z",
  "actor": "user:1050410410",
  "action": "shell_exec",
  "target": "ls -la /tmp",
  "severity": "critical",
  "payload_hash": "a1b2c3d4e5f6",
  "prev_hash": "f6e5d4c3b2a1..."
}
```

Verificar integridade: `/audit` no Telegram

---

## 🔧 Troubleshooting

### O bot não responde no Telegram

```bash
# 1. Verificar se está rodando
openpy status

# 2. Ver logs em tempo real
openpy logs

# 3. Testar token manualmente
curl -s "https://api.telegram.org/botSEU_TOKEN/getMe"

# 4. Verificar se seu ID está na allowlist
grep allowed_users /opt/open-py/openpy.toml
```

### Erro de conexão com PostgreSQL

```bash
# Verificar se está rodando
sudo systemctl status postgresql

# Reiniciar
sudo systemctl restart postgresql

# Testar conexão
sudo -u postgres psql -d openpy -c "SELECT 1"
```

### Reexecutar migrations

```bash
cd /opt/open-py
./venv/bin/python3 -c "
import asyncio
from shared.config import load_config
from shared.migrations import run_migrations
asyncio.run(run_migrations(load_config().database.dsn))
"
```

### Diagnóstico completo

```bash
openpy doctor
```

### Reinstalar completamente

```bash
openpy uninstall       # Remove tudo
sudo bash install.sh   # Reinstala do zero
```

---

## 📝 API de Referência

### Dependências Python (requirements.txt)

```
pydantic>=2.5         # Validação de dados
tomli>=2.0            # Parser TOML
tomli-w>=1.0          # Writer TOML
structlog>=24.0       # Logging estruturado
rich>=13.0            # Terminal bonito
asyncpg>=0.29         # PostgreSQL async
psutil>=5.9           # Métricas do sistema
aiofiles>=23.0        # File I/O async
aiohttp>=3.9          # HTTP client async
aiogram>=3.4          # Telegram Bot Framework
litellm>=1.30         # Multi-LLM Router
apscheduler>=3.10     # Task Scheduler
sentence-transformers>=2.5  # Embeddings locais
duckduckgo-search>=6.0      # Busca web gratuita
numpy>=1.26           # Operações vetoriais
pgvector>=0.2         # pgvector Python client
```

---

## 📋 Changelog

### v3.1.0 (Atual) — "Resilient Architecture & Context Compaction"

- 🗜️ **Context Compaction**: Compressão automática do buffer em RAM para LLM (evita overloads via 20 interações).
- 🧩 **Agent Creator Pipeline**: Pipeline de criação de agentes customizados agora 100% sob aprovação ("SIM"/"NÃO").
- 🧠 **Delegação Forçada / Intenção (Fase 7 e 8)**: Bypass avançado para intenção de tarefa ignorando conversinhas (*chit-chat*). Orquestrador e Router protegidos.
- 📆 **Rastreamento de Memória por HORA SOLAR**: Fix no salvamento cíclico dos arquivos MD (arquivos temporais mais estáveis `memory/md`).
- ⚡ **DB Resilients**: Correção nas colunas do PostgreSQL `pgvector`, isolando embeddings das memórias MD, não quebrando mais em inserts da engine base.
- 📝 **Comando `/remember`**: Adição de memória permanente diretamente pelo Telegram (importance: 10).

### v3.0.0 — "Hardened Brain"

- 🧠 **Memória Semântica**: busca contextual (pgvector) — só injeta memórias relevantes ao input atual
- 📦 **Message Batching**: agrupa mensagens em janela de 2s antes de processar
- 📋 **Task Queue**: fila obrigatória com prioridade (CRITICAL > HIGH > NORMAL > LOW)
- 🛡️ **Rate Limiter**: token bucket (1 msg/s, 20 msg/s global) + deduplicação
- 📝 **Audit Log Imutável**: chain SHA-256, append-only, comando `/audit`
- 🧠 **Auto-Learning**: salva tudo, extrai preferências, adapta comportamento
- 🔐 **SYSTEM_SECURITY Block**: regras de segurança nunca truncadas/comprimidas
- 🔐 **Context Compression Segura**: preserva início+fim, corta só histórico antigo
- 🔐 **Identity Versioning**: backup SHA-256 de soul.md e essence.md
- 🏥 **Fallback Routing**: cadeia automática de delegação se agente falha
- 💊 **Agent Healthcheck**: auto-desativação após 3 falhas, recovery após 5min
- 🚫 **Agent Quotas**: max 20 agentes, 5/hora, 10 custom
- 🏥 **Comando /health**: relatório completo de saúde via Telegram

### v2.2.0
- 🐍 Logo oficial do Open-PY
- 🔒 Licença migrada para AGPL-3.0
- 🔗 Base URLs pré-configuradas para todos os provedores
- 📦 pgvector com 3 fallbacks (apt → PGDG → compilação)

### v2.0.0
- 🧠 Thinking Engine com 4 camadas
- 🤖 6 agentes builtin com permissões granulares
- 💾 Memória em 3 camadas (RAM → MD → PostgreSQL)
- 🔐 Isolamento via Bubblewrap
- 📱 Frontend Telegram completo (aiogram 3.x)
- 🔄 Multi-provedor LLM com fallback (LiteLLM)
- 🩺 Sistema doctor com 14 checks e auto-reparo
- ⏰ Scheduler com heartbeat e migração diária
- 🧬 Identidade persistente (soul.md + essence.md)
- 📦 Instalador interativo com validação de token

---

## 📜 Licença

**AGPL-3.0** — Pode usar, modificar e distribuir livremente, **desde que mantenha o código aberto** e preserve os créditos do autor original.

Veja o arquivo [LICENSE](LICENSE) para detalhes completos.

---

<p align="center">
  <b>Feito com 🧠 por Open-PY Framework</b><br>
  <i>Copyright © 2026 faelsete. Todos os direitos reservados sob AGPL-3.0.</i>
</p>
