import logging
import time
from abc import ABC, abstractmethod

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

logger = logging.getLogger(__name__)


class BaseProvider(ABC):
    """Base interface for AI providers."""

    def __init__(self):
        self.last_usage = None
        self.last_response_time = None
        self.last_error_details = None

    @abstractmethod
    def generate(self, prompt):
        raise NotImplementedError

    def get_error_details(self, exc):
        return {
            'error_type': 'PROVIDER_ERROR',
            'message': str(exc) or type(exc).__name__,
            'retry_recommendation': 'Please try again later or switch to another configured provider.',
        }

    def get_usage_summary(self, usage):
        if usage is None:
            return None

        if isinstance(usage, dict):
            prompt_tokens = usage.get('prompt_tokens')
            completion_tokens = usage.get('completion_tokens')
            total_tokens = usage.get('total_tokens')
        else:
            prompt_tokens = getattr(usage, 'prompt_tokens', None)
            completion_tokens = getattr(usage, 'completion_tokens', None)
            total_tokens = getattr(usage, 'total_tokens', None)

        if prompt_tokens is None and completion_tokens is None and total_tokens is None:
            return str(usage)

        return f'prompt={prompt_tokens}, completion={completion_tokens}, total={total_tokens}'


class MockProvider(BaseProvider):
    """Simple mock provider used for local testing and compatibility."""

    def generate(self, prompt):
        return (
            '{"beginner_explanation":"A simple explanation of the paper.",'
            '"technical_explanation":"A technical explanation of the paper.",'
            '"key_contributions":["The paper presents a new approach."],'
            '"key_concepts":["Core concept"],'
            '"reading_difficulty":{"level":"Intermediate","reason":"It requires domain background."},'
            '"glossary":[{"term":"Model","simple_explanation":"A simplified representation","technical_explanation":"A formal abstraction used for analysis","example":"A model can help explain observations"}],'
            '"flashcards":[{"question":"What is the main idea?","answer":"The paper introduces a new approach."}],'
            '"viva_questions":[{"question":"What is the main contribution?","suggested_answer":"It proposes a new approach.","follow_up_question":"Why is it important?"}]}'
        )


class GroqProvider(BaseProvider):
    """Generic Groq provider that only sends prompts and returns responses."""

    def __init__(self):
        super().__init__()
        api_key = getattr(settings, 'GROQ_API_KEY', None)
        if not api_key:
            raise ImproperlyConfigured('GROQ_API_KEY is not configured.')

        try:
            import groq
            from groq import Groq
        except Exception as exc:  # pragma: no cover - environment-specific
            logger.exception('Failed to import groq SDK.')
            raise exc

        self.groq_module = groq
        self.client = Groq(api_key=api_key)
        self.model_name = getattr(settings, 'GROQ_MODEL', None) or 'llama-3.3-70b-versatile'

    def get_error_details(self, exc):
        groq_error_name = type(exc).__name__
        error_text = str(exc).strip().lower()

        if getattr(self.groq_module, 'RateLimitError', None) is not None and isinstance(exc, self.groq_module.RateLimitError):
            return {
                'error_type': 'RATE_LIMIT',
                'message': 'AI generation could not be completed because the configured AI provider has reached its usage limit. Please try again later or switch to another configured provider.',
                'retry_recommendation': 'Please try again later or switch to another configured provider.',
            }

        explicit_limit_markers = (
            'rate limit exceeded',
            'rate-limit exceeded',
            'usage limit exceeded',
            'quota exceeded',
            'exceeded your current quota',
            'too many requests',
            '429',
        )
        if any(marker in error_text for marker in explicit_limit_markers):
            return {
                'error_type': 'RATE_LIMIT',
                'message': 'AI generation could not be completed because the configured AI provider has reached its usage limit. Please try again later or switch to another configured provider.',
                'retry_recommendation': 'Please try again later or switch to another configured provider.',
            }

        if getattr(self.groq_module, 'AuthenticationError', None) is not None and isinstance(exc, self.groq_module.AuthenticationError):
            return {
                'error_type': 'AUTHENTICATION_ERROR',
                'message': 'Authentication with the AI provider failed. Please check the API configuration.',
                'retry_recommendation': 'Please verify the provider API configuration and try again.',
            }

        if getattr(self.groq_module, 'APIConnectionError', None) is not None and isinstance(exc, self.groq_module.APIConnectionError):
            return {
                'error_type': 'CONNECTION_ERROR',
                'message': 'Unable to connect to the AI provider. Please check your internet connection and try again.',
                'retry_recommendation': 'Please check your network connection and try again.',
            }

        if getattr(self.groq_module, 'BadRequestError', None) is not None and isinstance(exc, self.groq_module.BadRequestError):
            return {
                'error_type': 'BAD_REQUEST',
                'message': 'The AI provider rejected the request. Please verify the current configuration and try again.',
                'retry_recommendation': 'Please review the request configuration and try again.',
            }

        if getattr(self.groq_module, 'APIError', None) is not None and isinstance(exc, self.groq_module.APIError):
            return {
                'error_type': 'PROVIDER_ERROR',
                'message': 'The AI provider returned an unexpected error. Please try again later.',
                'retry_recommendation': 'Please try again later or switch to another configured provider.',
            }

        if isinstance(exc, TimeoutError) or groq_error_name == 'TimeoutError':
            return {
                'error_type': 'TIMEOUT',
                'message': 'The AI provider request timed out. Please try again later.',
                'retry_recommendation': 'Please try again later.',
            }

        if isinstance(exc, ConnectionError) or groq_error_name == 'ConnectionError':
            return {
                'error_type': 'CONNECTION_ERROR',
                'message': 'Unable to connect to the AI provider. Please check your internet connection and try again.',
                'retry_recommendation': 'Please check your network connection and try again.',
            }

        return super().get_error_details(exc)

    def generate(self, prompt):
        self.last_usage = None
        self.last_response_time = None
        start_time = time.perf_counter()
        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[{'role': 'user', 'content': prompt}],
                temperature=0.0,
            )
        except Exception as exc:
            self.last_error_details = self.get_error_details(exc)
            raise

        self.last_response_time = time.perf_counter() - start_time
        self.last_usage = getattr(response, 'usage', None)
        return self._extract_text(response)

    def _extract_text(self, response):
        text = ''
        try:
            if hasattr(response, 'choices') and response.choices:
                choice = response.choices[0]
                message = getattr(choice, 'message', None)
                if message is not None:
                    content = getattr(message, 'content', None)
                    if isinstance(content, list):
                        parts = []
                        for item in content:
                            if isinstance(item, str):
                                parts.append(item)
                            elif isinstance(item, dict):
                                parts.append(item.get('text', ''))
                        text = ''.join(parts)
                    elif isinstance(content, str):
                        text = content
                    else:
                        text = str(content)
                else:
                    text = str(response)
            else:
                text = str(response)
        except Exception:
            logger.exception('Failed to extract text from Groq response.')
            text = str(response)

        return (text or '').strip()
