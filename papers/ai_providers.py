import logging
from abc import ABC, abstractmethod

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

logger = logging.getLogger(__name__)


class BaseProvider(ABC):
    """Base interface for AI providers."""

    @abstractmethod
    def generate(self, prompt):
        raise NotImplementedError


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
        api_key = getattr(settings, 'GROQ_API_KEY', None)
        if not api_key:
            raise ImproperlyConfigured('GROQ_API_KEY is not configured.')

        try:
            from groq import Groq
        except Exception as exc:  # pragma: no cover - environment-specific
            logger.exception('Failed to import groq SDK.')
            raise exc

        self.client = Groq(api_key=api_key)
        self.model_name = getattr(settings, 'GROQ_MODEL', None) or 'llama-3.3-70b-versatile'

    def generate(self, prompt):
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=[{'role': 'user', 'content': prompt}],
            temperature=0.0,
        )
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
