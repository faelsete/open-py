"""
Open-PY v4.1 — Neural Thinking Engine
Raciocínio estruturado ANTES de agir.

O Core PENSA antes de executar. Não pergunta, não enrola.
Produz um plano em JSON (funciona com QUALQUER modelo).

Fluxo cognitivo:
  1. Analisar tarefa (o que precisa ser feito?)
  2. Consultar memória (já fiz isso antes? o que funcionou?)
  3. Avaliar abordagens (quais opções? qual é melhor e por quê?)
  4. Decompor em steps (uma tarefa ou várias?)
  5. Definir ferramentas (quais tools/agentes preciso?)
  6. Critérios de verificação (como sei que deu certo?)
  7. Pós-execução: salvar aprendizado na memória
"""

import json
import time
from typing import Optional
from dataclasses import dataclass, field

from shared.logger import get_logger

log = get_logger("neural")


# ============================================
# ESTRUTURAS DO PENSAMENTO
# ============================================

@dataclass
class ThoughtStep:
    """Um passo do plano de execução"""
    step_number: int
    action: str            # O que fazer
    tool: str = ""         # Tool a usar (se houver)
    agent: str = ""        # Agente a delegar (se houver)
    input_data: str = ""   # Dados de entrada
    expected_output: str = ""  # O que espero de resultado
    verification: str = "" # Como verificar se deu certo
    status: str = "pending"  # pending | running | done | failed
    result: str = ""       # Resultado real

    def to_dict(self) -> dict:
        return {
            "step": self.step_number,
            "action": self.action,
            "tool": self.tool,
            "agent": self.agent,
            "status": self.status,
        }


@dataclass
class ThoughtChain:
    """Cadeia de pensamento completa"""
    task_analysis: str = ""          # O que o usuário quer
    memory_check: str = ""           # O que achei na memória
    approach_reasoning: str = ""     # Raciocínio sobre abordagens
    chosen_approach: str = ""        # Abordagem escolhida
    steps: list[ThoughtStep] = field(default_factory=list)
    requires_sandbox: bool = False   # Precisa de ambiente isolado?
    is_multi_task: bool = False      # Mais de 1 tarefa?
    save_to_memory: bool = True      # Salvar resultado pra próxima vez?
    memory_tags: list[str] = field(default_factory=list)
    confidence: float = 0.0          # 0-1: quão confiante estou no plano
    thinking_time_ms: float = 0.0

    @property
    def total_steps(self) -> int:
        return len(self.steps)

    @property
    def completed_steps(self) -> int:
        return len([s for s in self.steps if s.status == "done"])

    @property
    def progress_pct(self) -> float:
        if not self.steps:
            return 100.0
        return round(self.completed_steps / self.total_steps * 100, 1)

    def to_dict(self) -> dict:
        return {
            "analysis": self.task_analysis,
            "approach": self.chosen_approach,
            "steps": [s.to_dict() for s in self.steps],
            "multi_task": self.is_multi_task,
            "sandbox": self.requires_sandbox,
            "confidence": self.confidence,
            "thinking_ms": self.thinking_time_ms,
        }


# ============================================
# PROMPT COGNITIVO — Força raciocínio estruturado
# ============================================

COGNITIVE_PROMPT = """Você é o CÉREBRO do Open-PY. Antes de executar QUALQUER tarefa, você PENSA.

Sua função: analisar a tarefa recebida e produzir um PLANO DE EXECUÇÃO em JSON.
NÃO execute nada. Apenas PENSE e PLANEJE.

## Regras do pensamento:
1. NUNCA pergunte ao usuário. DECIDA sozinho.
2. Se a tarefa tem múltiplas partes, decomponha em steps.
3. Se já existe uma solução na memória, REUTILIZE.
4. Prefira a abordagem mais SIMPLES que funcione.
5. Se precisa criar scripts, diga QUAL script criar no step.
6. Se precisa de ambiente isolado (arquivos, scripts), marque sandbox=true.
7. Sempre inclua um step de VERIFICAÇÃO no final.

## Memórias disponíveis (coisas que já fiz antes):
{memories}

## Ferramentas disponíveis:
{tools}

## Agentes disponíveis:
{agents}

## Tarefa recebida:
{task}

## Responda APENAS com JSON válido neste formato:
```json
{{
  "task_analysis": "O que o usuário quer em 1 frase",
  "memory_check": "O que achei relevante na memória (ou 'nada encontrado')",
  "approach_options": [
    "Opção 1: descrever",
    "Opção 2: descrever"
  ],
  "chosen_approach": "A melhor opção e POR QUÊ",
  "confidence": 0.85,
  "requires_sandbox": false,
  "is_multi_task": false,
  "save_to_memory": true,
  "memory_tags": ["audio", "corte", "ffmpeg"],
  "steps": [
    {{
      "step_number": 1,
      "action": "Descrição do que fazer",
      "tool": "nome_da_tool ou vazio",
      "agent": "nome_do_agente ou vazio",
      "input_data": "dados de entrada",
      "expected_output": "o que espero",
      "verification": "como verificar se deu certo"
    }}
  ]
}}
```"""


# ============================================
# POST-EXECUTION: Template de memória
# ============================================

LEARNING_TEMPLATE = """## Aprendizado salvo automaticamente

**Tarefa:** {task_summary}
**Abordagem:** {approach}
**Resultado:** {result_status}
**Steps executados:** {steps_done}/{steps_total}

### O que funcionou:
{what_worked}

### O que não funcionou:
{what_failed}

### Para próxima vez:
{next_time}

### Scripts/comandos úteis:
{useful_scripts}
"""


# ============================================
# NEURAL THINKING ENGINE
# ============================================

class NeuralEngine:
    """
    Motor de raciocínio neural.
    Pensa ANTES de agir. Produz planos estruturados.
    Funciona com QUALQUER modelo (usa JSON, não free-form).
    """

    def __init__(self, llm_router=None, memory_manager=None,
                 tool_registry=None, agent_registry=None):
        self.llm = llm_router
        self.memory = memory_manager
        self.tool_registry = tool_registry
        self.agent_registry = agent_registry

        # Cache de planos recentes (evita re-pensar tarefas iguais)
        self._plan_cache: dict[str, ThoughtChain] = {}
        self._max_cache = 50

        # Métricas
        self._total_thoughts = 0
        self._cache_hits = 0

    async def think(self, task: str, input_type: str = "text",
                    memories: list[dict] = None,
                    attachments: list[str] = None) -> ThoughtChain:
        """
        Raciocínio principal. Recebe tarefa, retorna plano.

        1. Verifica cache (tarefa idêntica recente)
        2. Monta contexto (memórias, tools, agentes)
        3. Chama LLM com prompt cognitivo
        4. Parseia resposta JSON
        5. Retorna ThoughtChain pronto para execução
        """
        start = time.perf_counter()
        self._total_thoughts += 1

        # === CACHE: tarefa idêntica recente? ===
        cache_key = task.strip().lower()[:200]
        if cache_key in self._plan_cache:
            self._cache_hits += 1
            cached = self._plan_cache[cache_key]
            log.info("🧠 Cache hit — reutilizando plano",
                     task=task[:60], confidence=cached.confidence)
            return cached

        # === CONTEXTO: montar informações disponíveis ===
        memory_text = self._format_memories(memories or [])
        tools_text = self._format_tools()
        agents_text = self._format_agents()

        # === PROMPT COGNITIVO ===
        prompt = COGNITIVE_PROMPT.format(
            memories=memory_text or "Nenhuma memória relevante encontrada.",
            tools=tools_text or "Nenhuma ferramenta carregada.",
            agents=agents_text or "Nenhum agente disponível.",
            task=task,
        )

        # === CHAMADA LLM ===
        try:
            messages = [
                {"role": "system", "content": "Você é um planejador. Responda APENAS JSON válido."},
                {"role": "user", "content": prompt},
            ]

            raw_response = await self.llm.complete(
                messages=messages,
                temperature=0.3,  # Baixa: queremos raciocínio estável
                max_tokens=2000,
            )

            # === PARSE JSON ===
            chain = self._parse_thought(raw_response, task)

        except Exception as e:
            log.warning(f"⚠️ Neural thinking falhou, criando plano básico: {e}")
            chain = self._fallback_plan(task, input_type, attachments)

        # Tempo de raciocínio
        chain.thinking_time_ms = round((time.perf_counter() - start) * 1000, 2)

        # Cachear plano
        if len(self._plan_cache) >= self._max_cache:
            # Remover mais antigo
            oldest = next(iter(self._plan_cache))
            del self._plan_cache[oldest]
        self._plan_cache[cache_key] = chain

        log.info("🧠 Pensamento concluído",
                 steps=chain.total_steps,
                 confidence=chain.confidence,
                 sandbox=chain.requires_sandbox,
                 multi_task=chain.is_multi_task,
                 thinking_ms=chain.thinking_time_ms)

        return chain

    def _parse_thought(self, raw: str, task: str) -> ThoughtChain:
        """Parseia resposta JSON do LLM em ThoughtChain"""
        # Extrair JSON do texto (pode vir com ```json ... ```)
        json_str = raw
        if "```json" in raw:
            json_str = raw.split("```json")[1].split("```")[0]
        elif "```" in raw:
            json_str = raw.split("```")[1].split("```")[0]

        # Tentar encontrar JSON no texto
        json_str = json_str.strip()
        if not json_str.startswith("{"):
            # Procurar primeiro { no texto
            idx = json_str.find("{")
            if idx >= 0:
                json_str = json_str[idx:]

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            log.warning("⚠️ Falha no parse JSON, usando fallback")
            return self._fallback_plan(task, "text")

        # Montar ThoughtChain
        chain = ThoughtChain(
            task_analysis=data.get("task_analysis", task[:100]),
            memory_check=data.get("memory_check", ""),
            approach_reasoning=str(data.get("approach_options", [])),
            chosen_approach=data.get("chosen_approach", ""),
            requires_sandbox=data.get("requires_sandbox", False),
            is_multi_task=data.get("is_multi_task", False),
            save_to_memory=data.get("save_to_memory", True),
            memory_tags=data.get("memory_tags", []),
            confidence=float(data.get("confidence", 0.7)),
        )

        # Montar steps
        for step_data in data.get("steps", []):
            step = ThoughtStep(
                step_number=step_data.get("step_number", 0),
                action=step_data.get("action", ""),
                tool=step_data.get("tool", ""),
                agent=step_data.get("agent", ""),
                input_data=step_data.get("input_data", ""),
                expected_output=step_data.get("expected_output", ""),
                verification=step_data.get("verification", ""),
            )
            chain.steps.append(step)

        return chain

    def _fallback_plan(self, task: str, input_type: str = "text",
                       attachments: list = None) -> ThoughtChain:
        """Plano básico quando o pensamento neural falha"""
        chain = ThoughtChain(
            task_analysis=task[:200],
            chosen_approach="Execução direta (fallback — pensamento neural falhou)",
            confidence=0.5,
        )
        chain.steps.append(ThoughtStep(
            step_number=1,
            action="Executar tarefa diretamente",
            tool="",
            expected_output="Resposta do LLM",
        ))
        return chain

    def _format_memories(self, memories: list[dict]) -> str:
        """Formata memórias para o prompt"""
        if not memories:
            return ""
        lines = []
        for mem in memories[:10]:
            content = mem.get("content", "")[:200]
            tags = mem.get("tags", [])
            source = mem.get("source", "")
            tag_str = f" [{', '.join(tags[:3])}]" if tags else ""
            lines.append(f"- {content}{tag_str} (via {source})")
        return "\n".join(lines)

    def _format_tools(self) -> str:
        """Lista tools disponíveis para o prompt"""
        if not self.tool_registry:
            return ""
        tools = self.tool_registry.list_all()
        lines = []
        for t in tools:
            danger = " ⚠️PERIGOSA" if t.get("dangerous") else ""
            lines.append(f"- {t['name']}: {t['description']}{danger} [{t['category']}]")
        return "\n".join(lines)

    def _format_agents(self) -> str:
        """Lista agentes disponíveis para o prompt"""
        if not self.agent_registry:
            return ""
        agents = self.agent_registry.list_all()
        lines = []
        for a in agents:
            lines.append(f"- {a.name}: {a.config.description} (model: {a.config.model})")
        return "\n".join(lines)

    # ============================================
    # PÓS-EXECUÇÃO: Aprender com o resultado
    # ============================================

    async def learn_from_execution(self, chain: ThoughtChain,
                                    final_result: str,
                                    success: bool = True):
        """
        Pós-execução: salvar aprendizado na memória.
        Grava O QUE funcionou, O QUE falhou, e COMO resolver na próxima vez.
        """
        if not chain.save_to_memory or not self.memory:
            return

        # Montar resumo do que funcionou / falhou
        worked = []
        failed = []
        useful_scripts = []

        for step in chain.steps:
            if step.status == "done":
                worked.append(f"Step {step.step_number}: {step.action}")
                if step.tool:
                    useful_scripts.append(f"Tool: {step.tool}")
            elif step.status == "failed":
                failed.append(f"Step {step.step_number}: {step.action} — {step.result}")

        learning = LEARNING_TEMPLATE.format(
            task_summary=chain.task_analysis[:200],
            approach=chain.chosen_approach[:200],
            result_status="✅ Sucesso" if success else "❌ Falha",
            steps_done=chain.completed_steps,
            steps_total=chain.total_steps,
            what_worked="\n".join(worked) or "—",
            what_failed="\n".join(failed) or "Nada falhou",
            next_time=chain.chosen_approach[:150] if success else "Tentar abordagem diferente",
            useful_scripts="\n".join(useful_scripts) or "—",
        )

        # Salvar na memória permanente
        try:
            tags = chain.memory_tags + ["neural_learning"]
            if success:
                tags.append("success")
            else:
                tags.append("failure")

            await self.memory.store(
                content=learning,
                category="neural_learning",
                tags=tags,
                metadata={
                    "confidence": chain.confidence,
                    "steps": chain.total_steps,
                    "approach": chain.chosen_approach[:100],
                }
            )
            log.info("💾 Aprendizado salvo na memória",
                     tags=tags, success=success)
        except Exception as e:
            log.warning(f"⚠️ Falha ao salvar aprendizado: {e}")

    # ============================================
    # MÉTRICAS
    # ============================================

    def get_metrics(self) -> dict:
        return {
            "total_thoughts": self._total_thoughts,
            "cache_hits": self._cache_hits,
            "cache_hit_rate": round(
                self._cache_hits / max(self._total_thoughts, 1) * 100, 1
            ),
            "cached_plans": len(self._plan_cache),
        }
