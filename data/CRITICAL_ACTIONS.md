# 🔒 Open-PY — Ações Críticas

## Ações que EXIGEM confirmação explícita do usuário

Qualquer ação nesta lista **deve ser confirmada via Telegram** antes de ser executada.
O sistema enviará: `⚠️ Ação sensível: [descrição]. Confirmar? (sim/não)`

### 🔴 NÍVEL CRÍTICO (Sempre confirmar)

| Ação | Comando/Trigger | Motivo |
|------|-----------------|--------|
| Deletar arquivos | `rm`, `unlink`, `shutil.rmtree` | Perda irreversível de dados |
| Executar comandos shell | `shell_exec`, `subprocess` | Risco de dano ao sistema |
| Criar/destruir agentes | `/spawn`, `/kill`, `agent_creator` | Consumo de recursos / perda de estado |
| Alterar soul.md | Edição direta | Corrompe identidade permanente |
| Alterar essence.md | Edição direta | Corrompe comportamento base |
| Drop/alter tabelas SQL | `DROP`, `ALTER TABLE`, `TRUNCATE` | Perda de dados do banco |
| Acessar rede externa | `http_client` com URLs externas | Exfiltração / exposição |
| Instalar pacotes | `pip install`, `apt install` | Modificação do ambiente |

### 🟡 NÍVEL ALTO (Confirmar se > limites)

| Ação | Limite Seguro | Acima = Confirmar |
|------|--------------|-------------------|
| Criar arquivos | < 10 por execução | ≥ 10 arquivos |
| Tokens por delegação | < 8000 tokens | ≥ 8000 tokens |
| Tempo de execução | < 5 minutos | ≥ 5 minutos |
| Memórias em batch | < 20 por vez | ≥ 20 memórias |

### 🟢 NÍVEL BAIXO (Apenas log)

- Leitura de arquivos
- Consultas SELECT no banco
- Busca em memórias
- Classificação de input
- Respostas diretas do Core

---

## Ações PROIBIDAS (Nunca executar)

| Ação | Motivo |
|------|--------|
| `rm -rf /` ou equivalente | Destruição do sistema |
| Alterar `/etc/passwd`, `/etc/shadow` | Escalação de privilégio |
| Modificar binários do sistema | Comprometimento do OS |
| Enviar credenciais para URLs externas | Vazamento de segredos |
| Fork bomb ou loops infinitos | DoS no próprio sistema |
| Acessar `openpy.toml` em logs/respostas | Exposição de API keys |
