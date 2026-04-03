"""
Open-PY — LLM Router
Wrapper sobre LiteLLM para unificar múltiplos provedores.
Suporta: OpenAI, Anthropic, OpenRouter, NVIDIA NIM, OpenCode (custom).
"""

from litellm import Router as LiteLLMRouter
from shared.config import OpenPYConfig
from shared.logger import get_logger
from shared.exceptions import NoProviderAvailableError

log = get_logger("llm-router")


class LLMRouter:
    """
    Router de provedores LLM usando LiteLLM.
    Fallback automático: se um provedor falha, tenta o próximo.
    """

    def __init__(self, config: OpenPYConfig):
        self.config = config
        model_list = []

        # OpenAI
        p = config.providers.openai
        if p.enabled and p.api_key:
            model_list.append({
                "model_name": "openai",
                "litellm_params": {
                    "model": config.core.default_model or "gpt-4o-mini",
                    "api_key": p.api_key,
                }
            })
            log.info("✅ OpenAI adicionado")

        # Anthropic
        p = config.providers.anthropic
        if p.enabled and p.api_key:
            model_list.append({
                "model_name": "anthropic",
                "litellm_params": {
                    "model": config.core.default_model or "claude-sonnet-4-20250514",
                    "api_key": p.api_key,
                }
            })
            log.info("✅ Anthropic adicionado")

        # OpenRouter
        p = config.providers.openrouter
        if p.enabled and p.api_key:
            model_list.append({
                "model_name": "openrouter",
                "litellm_params": {
                    "model": f"openrouter/{config.core.default_model or 'anthropic/claude-sonnet-4'}",
                    "api_key": p.api_key,
                }
            })
            log.info("✅ OpenRouter adicionado")

        # NVIDIA NIM
        p = config.providers.nvidia
        if p.enabled and p.api_key:
            model_list.append({
                "model_name": "nvidia",
                "litellm_params": {
                    "model": f"openai/{config.core.default_model or 'nvidia-model'}",
                    "api_base": p.api_base or "https://integrate.api.nvidia.com/v1",
                    "api_key": p.api_key,
                }
            })
            log.info("✅ NVIDIA NIM adicionado")

        # OpenCode (custom endpoint)
        p = config.providers.opencode
        if p.enabled and p.api_key and p.api_base:
            model_list.append({
                "model_name": "opencode",
                "litellm_params": {
                    "model": f"openai/{config.core.default_model or 'custom-model'}",
                    "api_base": p.api_base,
                    "api_key": p.api_key,
                }
            })
            log.info("✅ OpenCode adicionado")

        if not model_list:
            log.warning("⚠️ Nenhum provedor LLM configurado!")
            self.router = None
            self._available = False
            return

        self.router = LiteLLMRouter(
            model_list=model_list,
            retry_after=5,
            num_retries=2,
        )
        self._available = True
        self._model_names = [m["model_name"] for m in model_list]
        log.info(f"✅ LLM Router pronto com {len(model_list)} provedores: {self._model_names}")

    async def complete(self, messages: list, model: str = None,
                       max_tokens: int = 4096, temperature: float = 0.7,
                       **kwargs) -> str:
        """
        Chamada unificada com fallback entre provedores.
        model=None → usa o primeiro disponível.
        """
        if not self._available or not self.router:
            raise NoProviderAvailableError("Nenhum provedor LLM configurado")

        target_model = model or self._model_names[0]

        try:
            response = await self.router.acompletion(
                model=target_model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                **kwargs,
            )
            return response.choices[0].message.content

        except Exception as e:
            log.warning(f"⚠️ Falha no provedor {target_model}", error=str(e))

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
                        **kwargs,
                    )
                    return response.choices[0].message.content
                except Exception:
                    continue

            raise NoProviderAvailableError(
                f"Todos os provedores falharam: {self._model_names}"
            )
