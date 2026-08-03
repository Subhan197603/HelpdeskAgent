"""Allow-listed provider/model aliases resolved without database credentials."""

from apps.api.app.ai.providers import AnthropicProvider, LLMProvider, OpenAIProvider
from apps.api.app.core.settings import Settings


class UnknownProviderAliasError(ValueError):
    pass


class ProviderRegistry:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def resolve(self, provider_alias: str, model_alias: str) -> LLMProvider:
        if provider_alias == "openai":
            deployment = self._settings.openai_model_aliases.get(model_alias)
            secret = self._settings.openai_api_key
            if deployment is not None and secret is not None:
                return OpenAIProvider(
                    self._settings.openai_api_endpoint,
                    secret.get_secret_value(),
                    model_alias,
                    deployment,
                    self._settings.ai_provider_timeout_seconds,
                )
        elif provider_alias == "anthropic":
            deployment = self._settings.anthropic_model_aliases.get(model_alias)
            secret = self._settings.anthropic_api_key
            if deployment is not None and secret is not None:
                return AnthropicProvider(
                    self._settings.anthropic_api_endpoint,
                    secret.get_secret_value(),
                    model_alias,
                    deployment,
                    self._settings.ai_provider_timeout_seconds,
                )
        raise UnknownProviderAliasError("AI provider or model alias is not configured")
