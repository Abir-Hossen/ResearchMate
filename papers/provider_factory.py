from django.conf import settings

from .ai_providers import GroqProvider, MockProvider


class ProviderFactory:
    """Create the configured AI provider instance from Django settings."""

    @staticmethod
    def create_provider():
        provider_name = (getattr(settings, 'AI_PROVIDER', 'groq') or 'groq').strip().lower()

        if provider_name == 'groq':
            return GroqProvider()
        if provider_name == 'mock':
            return MockProvider()

        raise ValueError(f'Unsupported AI provider configured: {provider_name}')
