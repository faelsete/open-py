# 🔐 Política de Segurança — Open-PY

## Versões suportadas

| Versão | Suportada |
|--------|-----------|
| 2.2.x  | ✅ Sim    |
| < 2.0  | ❌ Não    |

## 🐛 Reportando uma vulnerabilidade

Se você encontrou uma vulnerabilidade de segurança no Open-PY, **NÃO abra uma Issue pública**.

### Como reportar

1. **Email:** Abra uma Issue com label `security` e marque como **confidencial**
2. Descreva a vulnerabilidade com o máximo de detalhes possível
3. Inclua passos para reproduzir, se possível
4. Aguarde uma resposta em até **48 horas**

### O que esperamos

- Dê tempo razoável para corrigirmos antes de divulgar publicamente
- Não explore a vulnerabilidade além do necessário para demonstrá-la
- Não acesse dados de outros usuários

### O que garantimos

- ✅ Reconhecimento público da descoberta (se desejado)
- ✅ Correção priorizada dentro de 7 dias para vulnerabilidades críticas
- ✅ Comunicação transparente sobre o progresso da correção

## 🛡️ Práticas de segurança do Open-PY

- Credenciais são armazenadas em `openpy.toml` com permissões `600`
- O arquivo de configuração **nunca** é versionado (está no `.gitignore`)
- Agentes rodam em **sandbox** via Bubblewrap (`bwrap`)
- Conexões com o banco usam **senhas geradas automaticamente**
- API keys são passadas apenas via variáveis de ambiente
