"""
Open-PY — Quality Gate (Validator) v3.0
Verifica resposta antes do envio ao Telegram.

3 verificações:
1. SECURITY:  Vaza dados sensíveis? Viola SYSTEM_SECURITY?
2. RELEVANCE: Responde à pergunta original?
3. FACTUAL:   Contém invenções óbvias? (hallucination check leve)

Inspirado em: Claude Code SessionMemory + forked agent isolation.
O validator usa um prompt separado e curto para minimizar latência.
"""

import re
import json
from typing import Optional

from shared.models import ValidatorVerdict
from shared.config import ValidatorConfig
from shared.logger import get_logger

log = get_logger("validator")

# Padrões regex para detecção rápida de vazamentos (sem LLM)
LEAK_PATTERNS = [
    re.compile(r'(?:api[_-]?key|token|secret|password)\s*[=:]\s*["\']?[\w\-]{10,}', re.IGNORECASE),
    re.compile(r'sk-[a-zA-Z0-9]{20,}'),                    # OpenAI key
    re.compile(r'ghp_[a-zA-Z0-9]{36,}'),                    # GitHub PAT
    re.compile(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b'),  # IP addresses
    re.compile(r'(?:postgresql|mysql|mongodb)://\S+:\S+@'),   # DB connection strings
]

# Padrões de comandos destrutivos
DESTRUCTIVE_PATTERNS = [
    re.compile(r'rm\s+(-rf?|--recursive)\s+/', re.IGNORECASE),
    re.compile(r'DROP\s+(DATABASE|TABLE|SCHEMA)', re.IGNORECASE),
    re.compile(r'FORMAT\s+[A-Z]:', re.IGNORECASE),
    re.compile(r'dd\s+if=.*of=/dev/', re.IGNORECASE),
]

VALIDATION_PROMPT = """Você é um auditor de qualidade. Analise APENAS:

PERGUNTA DO USUÁRIO: "{question}"

RESPOSTA GERADA: "{response}"

Verifique:
1. A resposta é RELEVANTE à pergunta? (responde o que foi perguntado)
2. A resposta parece conter informação INVENTADA? (dados, links, nomes falsos)
3. A resposta é CLARA e DIRETA? (sem enrolação desnecessária)

Responda EXATAMENTE neste formato JSON:
{{"approved": true/false, "confidence": 0.0-1.0, "issues": ["lista de problemas se houver"], "suggestion": "sugestão de melhoria ou null"}}"""


class ResponseValidator:
    """
    Quality Gate: valida respostas antes do envio.
    
    Arquitetura em 2 camadas:
    1. Validação RÁPIDA (regex, sem LLM): ~0ms
       - Detecta vazamento de API keys, senhas, IPs
       - Detecta comandos destrutivos
    2. Validação SEMÂNTICA (LLM): ~300-800ms
       - Relevância, clareza, alucinações
       - Usa modelo barato/rápido
    """

    def __init__(self, config: ValidatorConfig, llm_router=None):
        self.config = config
        self.llm = llm_router
        self._total_checks = 0
        self._total_rejections = 0

    async def validate(self, question: str, response: str) -> ValidatorVerdict:
        """
        Validação completa em 2 camadas.
        Retorna ValidatorVerdict com approved/rejected + motivos.
        """
        self._total_checks += 1

        # === CAMADA 1: Validação rápida (regex, sem LLM) ===
        quick_result = self._quick_validate(response)
        if not quick_result.approved:
            self._total_rejections += 1
            log.warning("🔴 Resposta REJEITADA (quick check)",
                       issues=quick_result.issues)
            return quick_result

        # === CAMADA 2: Validação semântica (LLM) ===
        if self.config.enabled and self.llm and len(response) >= self.config.min_response_length:
            semantic_result = await self._semantic_validate(question, response)
            if not semantic_result.approved:
                self._total_rejections += 1
                log.warning("🟡 Resposta REJEITADA (semantic check)",
                           issues=semantic_result.issues,
                           confidence=semantic_result.confidence)
            return semantic_result

        # Sem validação semântica — aprovado por padrão
        return ValidatorVerdict(
            approved=True,
            confidence=0.8,
            check_type="quick_only"
        )

    def _quick_validate(self, response: str) -> ValidatorVerdict:
        """Validação instantânea via regex"""
        issues = []

        # Checar vazamentos de credenciais
        for pattern in LEAK_PATTERNS:
            matches = pattern.findall(response)
            if matches:
                issues.append(f"Possível vazamento de dados sensíveis detectado")
                break  # Um match já é suficiente

        # Checar comandos destrutivos
        for pattern in DESTRUCTIVE_PATTERNS:
            if pattern.search(response):
                issues.append("Resposta contém comando potencialmente destrutivo")
                break

        if issues:
            return ValidatorVerdict(
                approved=False,
                confidence=1.0,
                issues=issues,
                suggestion="Remover dados sensíveis ou comandos destrutivos da resposta",
                check_type="security"
            )

        return ValidatorVerdict(approved=True, confidence=1.0, check_type="quick")

    async def _semantic_validate(self, question: str, response: str) -> ValidatorVerdict:
        """Validação via LLM (modelo barato)"""
        try:
            # Truncar para economizar tokens
            q_truncated = question[:500]
            r_truncated = response[:1500]

            prompt = VALIDATION_PROMPT.format(
                question=q_truncated,
                response=r_truncated,
            )

            model = self.config.model if self.config.model else None
            raw = await self.llm.complete(
                messages=[{"role": "user", "content": prompt}],
                model=model,
                max_tokens=200,
                temperature=0.0,
            )

            # Parse do JSON de resposta
            return self._parse_verdict(raw)

        except Exception as e:
            log.warning("⚠️ Validação semântica falhou, aprovando por padrão",
                       error=str(e))
            return ValidatorVerdict(
                approved=True,
                confidence=0.5,
                check_type="semantic_error",
                issues=[f"Validação falhou: {str(e)[:100]}"]
            )

    def _parse_verdict(self, raw: str) -> ValidatorVerdict:
        """Parse robusto do JSON de resposta do LLM"""
        try:
            # Extrair JSON do markdown se necessário
            json_match = re.search(r'\{[^{}]+\}', raw, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
            else:
                data = json.loads(raw)

            approved = data.get("approved", True)
            confidence = float(data.get("confidence", 0.8))

            # Aplicar threshold de confiança
            if approved and confidence < self.config.min_confidence:
                approved = False

            return ValidatorVerdict(
                approved=approved,
                confidence=confidence,
                issues=data.get("issues", []),
                suggestion=data.get("suggestion"),
                check_type="semantic"
            )
        except (json.JSONDecodeError, ValueError):
            # Fallback: se não parseou, aprova
            log.debug("⚠️ Não conseguiu parsear verdict do LLM, aprovando")
            return ValidatorVerdict(
                approved=True,
                confidence=0.6,
                check_type="parse_fallback"
            )

    def get_stats(self) -> dict:
        """Estatísticas do validator"""
        return {
            "total_checks": self._total_checks,
            "total_rejections": self._total_rejections,
            "rejection_rate": round(
                self._total_rejections / max(self._total_checks, 1) * 100, 1
            ),
        }
