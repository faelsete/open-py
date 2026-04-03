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

    def __init__(self, config: OpenPYConfig):
        self.config = config
        self._model_list = []
        self._active_provider: str = ""
        self._active_model: str = config.core.default_model or ""

        # Mapeamento provedor → modelo atual
        self._provider_models: dict[str, str] = {}

        # OpenAI
        p = config.providers.openai
        if p.enabled and p.api_key:
            self._add_to_list("openai", config.core.default_model or "gpt-4o-mini", p.api_key)

        # Anthropic
        p = config.providers.anthropic
        if p.enabled and p.api_key:
            self._add_to_list("anthropic", config.core.default_model or "claude-sonnet-4-20250514", p.api_key)

        # OpenRouter
        p = config.providers.openrouter
        if p.enabled and p.api_key:
            model = config.core.default_model or "anthropic/claude-sonnet-4"
            self._add_to_list("openrouter", f"openrouter/{model}", p.api_key)

        # NVIDIA NIM
        p = config.providers.nvidia
        if p.enabled and p.api_key:
            self._add_to_list(
                "nvidia",
                f"openai/{config.core.default_model or 'nvidia-model'}",
                p.api_key,
                api_base=p.api_base or "https://integrate.api.nvidia.com/v1",
            )

        # OpenCode (custom endpoint)
        p = config.providers.opencode
        if p.enabled and p.api_key and p.api_base:
            self._add_to_list(
                "opencode",
                f"openai/{config.core.default_model or 'custom-model'}",
                p.api_key,
                api_base=p.api_base,
            )

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

        # Definir modelo padrão por provedor
        default_models = {
            "openai": "gpt-4o-mini",
            "anthropic": "claude-sonnet-4-20250514",
            "openrouter": "openrouter/qwen/qwen3-235b-a22b:free",
            "nvidia": "openai/nvidia-model",
            "opencode": "openai/custom-model",
        }

        llm_model = model or default_models.get(name, f"openai/{name}")

        # Se for openrouter e modelo não tem prefixo, adicionar
        if name == "openrouter" and not llm_model.startswith("openrouter/"):
            llm_model = f"openrouter/{llm_model}"

        self._add_to_list(name, llm_model, api_key, api_base)
        self._rebuild_router()

        # Persistir no config
        try:
            provider_cfg = ProviderConfig(api_key=api_key, api_base=api_base or "", enabled=True)
            if hasattr(self.config.providers, name):
                setattr(self.config.providers, name, provider_cfg)
                save_config(self.config)
        except Exception as e:
            log.warning("Config save failed", error=str(e))

        return {"ok": True, "message": f"✅ Provedor '{name}' adicionado com modelo '{llm_model}'"}

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

        # Aplicar prefixo se necessário
        if target == "openrouter" and not model.startswith("openrouter/"):
            model = f"openrouter/{model}"
        elif target in ("nvidia", "opencode") and not model.startswith("openai/"):
            model = f"openai/{model}"

        # Atualizar na lista
        for entry in self._model_list:
            if entry["model_name"] == target:
                entry["litellm_params"]["model"] = model
                break

        self._provider_models[target] = model
        self._active_model = model
        self._rebuild_router()

        # Persistir
        try:
            self.config.core.default_model = model
            save_config(self.config)
        except Exception as e:
            log.warning("Config save failed", error=str(e))

        return {"ok": True, "message": f"✅ Modelo do **{target}** alterado para: `{model}`"}

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
