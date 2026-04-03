# 🤝 Contribuindo com o Open-PY

Obrigado por considerar contribuir com o Open-PY! Este guia vai te ajudar a começar.

## 📋 Antes de começar

1. Faça um **fork** do repositório
2. Clone seu fork localmente
3. Crie uma **branch** para sua mudança: `git checkout -b feature/minha-feature`

## 🔧 Configurando o ambiente de desenvolvimento

```bash
# Clone seu fork
git clone https://github.com/SEU_USER/open-py.git
cd open-py

# Crie o ambiente virtual
python3 -m venv venv
source venv/bin/activate

# Instale as dependências
pip install -r requirements.txt
```

## ✅ Tipos de contribuição aceitos

| Tipo | Descrição |
|------|-----------|
| 🐛 **Bug fix** | Correção de bugs com testes |
| ✨ **Feature** | Novas funcionalidades úteis |
| 📝 **Docs** | Melhoria na documentação |
| 🔧 **Refactor** | Melhoria de código sem mudar funcionalidade |
| 🌍 **Tradução** | Suporte a novos idiomas |
| 🤖 **Agentes** | Novos agentes especializados |
| 🔌 **Provedores** | Suporte a novos provedores LLM |

## 📐 Padrões de código

- **Python 3.10+** com type hints
- **Docstrings** em todas as funções públicas
- **Snake_case** para variáveis e funções
- **PascalCase** para classes
- Linhas com máximo de **100 caracteres**
- Use `asyncio` para operações I/O

## 🚀 Enviando sua contribuição

1. **Commit** com mensagens descritivas:
   ```
   feat: adiciona agente de análise de imagens
   fix: corrige timeout na conexão com PostgreSQL
   docs: atualiza guia de instalação
   ```

2. **Push** para seu fork: `git push origin feature/minha-feature`

3. Abra um **Pull Request** descrevendo:
   - O que foi feito
   - Por que foi feito
   - Como testar

## ⚠️ Regras importantes

- **Nunca** commite credenciais, tokens ou API keys
- **Nunca** altere a licença (AGPL-3.0)
- **Sempre** mantenha o copyright do autor original
- Teste suas mudanças antes de abrir PR
- Siga o código de conduta

## 💬 Dúvidas?

Abra uma **Issue** com a label `question`.

---

**Obrigado por contribuir! 🐍**
