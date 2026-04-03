# 🧠 Open-PY — Framework de Agentes Autônomos

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
| 💾 **Memória em 3 Camadas** | Contexto (RAM) → Memory.md (filesystem) → PostgreSQL (longo prazo) |
| 🔐 **Isolamento Seguro** | Bubblewrap (bwrap) para sandboxing de agentes sem peso do Docker |
| 📱 **Frontend Telegram** | Interface completa com 10+ comandos e suporte a mídias |
| 🔄 **Multi-Provedor LLM** | OpenAI, Anthropic, OpenRouter, NVIDIA NIM, Custom (com fallback automático) |
| 🩺 **Auto-Diagnóstico** | 14 checks de saúde + reparo automático via `/doctor` |
| ⏰ **Scheduler** | Heartbeat, migração diária de memórias, cron jobs |
| 🧬 **Identidade Persistente** | soul.md (memória inalterável) + essence.md (personalidade) |

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
1. Usuário envia mensagem no Telegram
2. Bot recebe e encaminha ao Core
3. Core classifica o tipo (text/image/audio/video/code/command)
4. Core avalia urgência (critical/high/normal/low)
5. Core decide: responder direto OU delegar para agente
6. Se delegado → agente executa com suas ferramentas permitidas
7. Resultado volta ao Core → formata → envia ao Telegram
8. Interação é salva no buffer de memória
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
| `/memory` | Estatísticas de memória | — |
| `/agents` | Listar agentes ativos | — |
| `/tasks` | Tarefas em andamento | — |
| `/remember <texto>` | Salvar memória manualmente | `/remember Meu IP é 192.168.1.1` |
| `/recall <busca>` | Buscar nas memórias | `/recall qual meu IP` |
| `/soul` | Ver memória permanente | — |
| `/essence` | Ver personalidade atual | — |

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

### Tags automáticas

O sistema extrai tags automaticamente baseado em palavras-chave:
- `python`, `javascript`, `api`, `database`, `docker`, `git`, `linux`, `nginx`, etc.

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
│   ├── orchestrator.py       # Delegação e monitoramento de tarefas
│   └── lifecycle.py          # Startup (10 passos) / Shutdown
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
| **Bubblewrap sandbox** | Agentes rodam isolados via Linux namespaces |
| **Permissões mínimas** | Cada agente tem apenas as ferramentas que precisa |
| **Config protegido** | `openpy.toml` tem permissão `600` (só root lê) |
| **Senha auto-gerada** | Senha do PostgreSQL gerada com `openssl rand` |
| **Shell timeout** | Comandos shell têm timeout de 30s por padrão |
| **Sem Docker** | Isolamento via bwrap — mais leve e direto no Linux |

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

### v2.0.0 (Atual)
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

MIT License — Use livremente.

---

<p align="center">
  <b>Feito com 🧠 por Open-PY Framework</b>
</p>
