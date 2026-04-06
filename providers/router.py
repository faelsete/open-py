"""
Open-PY — LLM Router
Wrapper sobre LiteLLM para unificar múltiplos provedores.
Suporta: OpenAI, Anthropic, OpenRouter, NVIDIA NIM, OpenCode (custom).
"""

from litellm import Router as LiteLLMRouter
from shared.config import OpenPYConfig, ProviderConfig, save_config
from shared.logger import get_logger
from shared.exceptions import NoProviderAvailableError

log = get_logger("llm-router")


class LLMRouter:
    """
    Router de provedores LLM usando LiteLLM.
    Fallback automático: se um provedor falha, tenta o próximo.
    Suporta adição/remoção/troca de provedores em runtime.
    """

    # Modelos padrão por provedor (sem prefixo LiteLLM)
    DEFAULT_MODELS = {
        "openai": "gpt-4o-mini",
        "anthropic": "claude-sonnet-4-20250514",
        "openrouter": "qwen/qwen3-235b-a22b:free",
        "nvidia": "nvidia-model",
        "opencode": "custom-model",
    }

    # Prefixos exigidos pelo LiteLLM para cada provedor
    LITELLM_PREFIXES = {
        "openai": "",           # OpenAI não precisa de prefixo
        "anthropic": "",        # Anthropic não precisa de prefixo
        "openrouter": "openrouter/",
        "nvidia": "openai/",    # NVIDIA usa endpoint OpenAI-compatible
        "opencode": "openai/",  # Custom endpoint OpenAI-compatible
    }

    def __init__(self, config: OpenPYConfig):
        self.config = config
        self._model_list = []
        self._active_provider: str = ""
        self._active_model: str = ""

        # Mapeamento provedor → modelo LiteLLM completo (com prefixo)
        self._provider_models: dict[str, str] = {}

        # Inicializar cada provedor com seu modelo específico
        providers_map = {
            "openai": config.providers.openai,
            "anthropic": config.providers.anthropic,
            "openrouter": config.providers.openrouter,
            "nvidia": config.providers.nvidia,
            "opencode": config.providers.opencode,
        }

        for name, p in providers_map.items():
            if not (p.enabled and p.api_key):
                continue
            if name == "opencode" and not p.api_base:
                continue

            # Modelo: prioridade → p.model > config.core.default_model > DEFAULT
            raw_model = p.model or self.DEFAULT_MODELS.get(name, "")
            litellm_model = self._apply_prefix(name, raw_model)

            kwargs = {}
            if name == "nvidia":
                kwargs["api_base"] = p.api_base or "https://integrate.api.nvidia.com/v1"
            elif name == "opencode":
                kwargs["api_base"] = p.api_base

            self._add_to_list(name, litellm_model, p.api_key, **kwargs)

        self._rebuild_router()

    def _add_to_list(self, name: str, model: str, api_key: str, api_base: str = None):
        """Adiciona provedor à lista interna"""
        entry = {
            "model_name": name,
            "litellm_params": {
                "model": model,
                "api_key": api_key,
            }
        }
        if api_base:
            entry["litellm_params"]["api_base"] = api_base
        self._model_list.append(entry)
        self._provider_models[name] = model
        log.info(f"✅ {name} adicionado (modelo: {model})")

    def _rebuild_router(self):
        """Reconstrói o LiteLLM Router com a lista atual"""
        if not self._model_list:
            log.warning("⚠️ Nenhum provedor LLM configurado!")
            self.router = None
            self._available = False
            self._model_names = []
            return

        self.router = LiteLLMRouter(
            model_list=self._model_list,
            retry_after=5,
            num_retries=2,
        )
        self._available = True
        self._model_names = [m["model_name"] for m in self._model_list]
        if not self._active_provider:
            self._active_provider = self._model_names[0]
        log.info(f"✅ LLM Router pronto com {len(self._model_list)} provedores: {self._model_names}")

    # ============================================
    # PREFIXAÇÃO — Lógica centralizada
    # ============================================

    def _apply_prefix(self, provider_name: str, raw_model: str) -> str:
        """Aplica prefixo LiteLLM ao modelo, SEM duplicar"""
        prefix = self.LITELLM_PREFIXES.get(provider_name, "")
        if not prefix:
            return raw_model
        # Evitar prefixo duplicado
        if raw_model.startswith(prefix):
            return raw_model
        return f"{prefix}{raw_model}"

    def _strip_prefix(self, provider_name: str, model: str) -> str:
        """Remove prefixo LiteLLM para obter o modelo limpo"""
        prefix = self.LITELLM_PREFIXES.get(provider_name, "")
        if prefix and model.startswith(prefix):
            return model[len(prefix):]
        return model

    # ============================================
    # GERENCIAMENTO DINÂMICO
    # ============================================

    def add_provider(self, name: str, api_key: str, model: str = None,
                     api_base: str = None) -> dict:
        """
        Adiciona provedor em runtime.
        Retorna {"ok": bool, "message": str}
        """
        # Verificar se já existe
        if name in self._provider_models:
            return {"ok": False, "message": f"Provedor '{name}' já existe. Use /provider {name} para ativar."}

        # Modelo: argumento > default do provedor > genérico
        raw_model = model or self.DEFAULT_MODELS.get(name, f"{name}-model")
        clean_model = self._strip_prefix(name, raw_model)
        litellm_model = self._apply_prefix(name, clean_model)

        self._add_to_list(name, litellm_model, api_key, api_base)
        self._rebuild_router()

        # Persistir no config
        try:
            provider_cfg = ProviderConfig(
                api_key=api_key, api_base=api_base or "",
                enabled=True, model=clean_model,
            )
            if hasattr(self.config.providers, name):
                setattr(self.config.providers, name, provider_cfg)
                save_config(self.config)
        except Exception as e:
            log.warning("Config save failed", error=str(e))

        return {"ok": True, "message": f"✅ Provedor '{name}' adicionado com modelo '{litellm_model}'"}

    def remove_provider(self, name: str) -> dict:
        """Remove provedor em runtime"""
        if name not in self._provider_models:
            return {"ok": False, "message": f"Provedor '{name}' não encontrado."}

        self._model_list = [m for m in self._model_list if m["model_name"] != name]
        del self._provider_models[name]

        if self._active_provider == name:
            self._active_provider = self._model_names[0] if self._model_names else ""

        self._rebuild_router()
        return {"ok": True, "message": f"✅ Provedor '{name}' removido."}

    def set_active_provider(self, name: str) -> dict:
        """Troca o provedor ativo"""
        if name not in self._provider_models:
            available = ", ".join(self._provider_models.keys()) or "nenhum"
            return {"ok": False, "message": f"Provedor '{name}' não encontrado.\nDisponíveis: {available}"}

        self._active_provider = name
        return {"ok": True, "message": f"✅ Provedor ativo: **{name}** (modelo: {self._provider_models[name]})"}

    def set_model(self, model: str, provider: str = None) -> dict:
        """Troca o modelo de um provedor (ou do ativo)"""
        target = provider or self._active_provider
        if not target:
            return {"ok": False, "message": "Nenhum provedor ativo."}
        if target not in self._provider_models:
            return {"ok": False, "message": f"Provedor '{target}' não encontrado."}

        # Guardar modelo limpo (sem prefixo) para persistência
        clean_model = self._strip_prefix(target, model)

        # Aplicar prefixo LiteLLM
        litellm_model = self._apply_prefix(target, clean_model)

        # Atualizar na lista
        for entry in self._model_list:
            if entry["model_name"] == target:
                entry["litellm_params"]["model"] = litellm_model
                break

        self._provider_models[target] = litellm_model
        self._active_model = litellm_model
        self._rebuild_router()

        # Persistir PER-PROVIDER (não global)
        try:
            if hasattr(self.config.providers, target):
                provider_cfg = getattr(self.config.providers, target)
                provider_cfg.model = clean_model  # Salva SEM prefixo
                save_config(self.config)
                log.info(f"💾 Modelo salvo para {target}: {clean_model}")
        except Exception as e:
            log.warning("Config save failed", error=str(e))

        return {"ok": True, "message": f"✅ Modelo do **{target}** alterado para: `{litellm_model}`"}

    def list_providers(self) -> list[dict]:
        """Lista todos os provedores configurados"""
        result = []
        for name, model in self._provider_models.items():
            result.append({
                "name": name,
                "model": model,
                "active": name == self._active_provider,
            })
        return result

    def get_current_info(self) -> dict:
        """Info do provedor/modelo ativos"""
        return {
            "provider": self._active_provider,
            "model": self._provider_models.get(self._active_provider, "N/A"),
            "total_providers": len(self._provider_models),
            "available": self._available,
        }

    # ============================================
    # COMPLETION
    # ============================================

    async def complete(self, messages: list, model: str = None,
                       max_tokens: int = 4096, temperature: float = 0.7,
                       **kwargs) -> str:
        """
        Chamada unificada com fallback entre provedores.
        model=None → usa o provedor ativo.
        """
        if not self._available or not self.router:
            raise NoProviderAvailableError("Nenhum provedor LLM configurado")

        target_model = model or self._active_provider or self._model_names[0]

        try:
            log.info(f"🚀 Chamada LLM: {target_model}")
            response = await self.router.acompletion(
                model=target_model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                request_timeout=60,  # Timeout de 60s
                **kwargs,
            )
            return response.choices[0].message.content

        except Exception as e:
            log.warning(f"⚠️ Falha no provedor {target_model}: {str(e)}")

            # Tentar fallback para outros provedores
            for fallback in self._model_names:
                if fallback == target_model:
                    continue
                try:
                    log.info(f"🔄 Tentando fallback: {fallback}")
                    response = await self.router.acompletion(
                        model=fallback,
                        messages=messages,
                        max_tokens=max_tokens,
                        temperature=temperature,
                        request_timeout=60,  # Timeout no fallback também
                        **kwargs,
                    )
                    return response.choices[0].message.content
                except Exception as ef:
                    log.error(f"❌ Falha no fallback {fallback}: {str(ef)}")
                    continue

            raise NoProviderAvailableError(
                f"Todos os provedores falharam: {self._model_names}"
            )

    async def complete_with_tools(self, messages: list, tools: list[dict],
                                  model: str = None, max_tokens: int = 4096,
                                  temperature: float = 0.7,
                                  tool_choice: str = "auto",
                                  **kwargs) -> dict:
        """
        v4.0: Chamada LLM COM suporte a function calling.
        
        Retorna dict com:
        - "content": texto da resposta (ou None se tool_call)
        - "tool_calls": lista de tool calls [{id, function: {name, arguments}}]
        - "finish_reason": "stop" | "tool_calls"
        
        Args:
            tools: Lista de schemas OpenAI (output de tools_to_schemas)
            tool_choice: "auto" | "required" | "none" | {"type": "function", "function": {"name": "X"}}
        """
        if not self._available or not self.router:
            raise NoProviderAvailableError("Nenhum provedor LLM configurado")

        target_model = model or self._active_provider or self._model_names[0]

        call_kwargs = {
            "model": target_model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "request_timeout": 90,
            **kwargs,
        }

        # Só enviar tools se lista não vazia
        if tools:
            call_kwargs["tools"] = tools
            call_kwargs["tool_choice"] = tool_choice

        try:
            log.info(f"🔧 LLM + Tools: {target_model} ({len(tools)} tools)")
            response = await self.router.acompletion(**call_kwargs)
            
            choice = response.choices[0]
            message = choice.message

            result = {
                "content": message.content,
                "tool_calls": None,
                "finish_reason": choice.finish_reason,
            }

            # Extrair tool_calls se existirem
            if hasattr(message, "tool_calls") and message.tool_calls:
                result["tool_calls"] = [
                    {
                        "id": tc.id,
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        }
                    }
                    for tc in message.tool_calls
                ]
                result["finish_reason"] = "tool_calls"

            return result

        except Exception as e:
            log.warning(f"⚠️ Tool calling falhou: {e}")
            # Fallback: chamar sem tools (texto puro)
            try:
                fallback = await self.complete(messages=messages, model=model,
                                               max_tokens=max_tokens,
                                               temperature=temperature)
                return {
                    "content": fallback,
                    "tool_calls": None,
                    "finish_reason": "stop",
                }
            except Exception:
                raise

