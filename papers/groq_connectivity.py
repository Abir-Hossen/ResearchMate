"""Minimal Groq connectivity test service.

This service is intentionally isolated from the learning pipeline and only
verifies that a configured Groq API key can be used to send a tiny prompt.
It does not create models or parse AI output into the database.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

logger = logging.getLogger(__name__)


class GroqLearningService:
    """Thin wrapper around the official Groq Python SDK."""

    def __init__(self):
        api_key = getattr(settings, 'GROQ_API_KEY', None) or os.environ.get('GROQ_API_KEY')
        if not api_key:
            logger.error('No GROQ_API_KEY found in settings or environment.')
            raise ImproperlyConfigured('GROQ_API_KEY is not configured. Create a .env file or set the environment variable.')

        logger.info('Groq API key detected in environment (not displayed).')

        self.model_name = getattr(settings, 'GROQ_MODEL', None) or os.environ.get('GROQ_MODEL', 'llama-3.3-70b-versatile')
        logger.info('Using Groq model %s', self.model_name)

        try:
            from groq import Groq
        except Exception as exc:  # pragma: no cover - environment-specific
            logger.exception('Failed to import groq SDK.')
            raise exc

        self.client = Groq(api_key=api_key)

    def test_connection(self) -> Dict[str, Any]:
        """Send a tiny prompt and return the plain text response and timing."""
        prompt = 'Reply with exactly:\nResearchMate Groq Connected'

        logger.info('Request sent to Groq model %s: %s', self.model_name, prompt)
        start = time.perf_counter()

        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[{'role': 'user', 'content': prompt}],
                temperature=0.0,
            )
        except Exception:
            logger.exception('Groq request failed.')
            raise

        elapsed = time.perf_counter() - start
        logger.info('Groq responded in %.3fs', elapsed)

        text = self._extract_text(response)
        text = (text or '').strip()
        logger.info('Groq raw response: %s', text[:200])

        return {'model': self.model_name, 'response': text, 'elapsed': elapsed}

    def generate(self, prompt: str) -> str:
        """Send a prompt to Groq and return the plain text response."""
        return self.generate_analysis(prompt)

    def generate_analysis(self, prompt: str) -> str:
        """Send a prompt to Groq and return the plain text response."""
        logger.info('Request sent to Groq model %s: %s', self.model_name, prompt)
        start = time.perf_counter()

        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[{'role': 'user', 'content': prompt}],
                temperature=0.0,
            )
        except Exception:
            logger.exception('Groq request failed during generate_analysis.')
            raise

        elapsed = time.perf_counter() - start
        logger.info('Groq responded in %.3fs', elapsed)
        text = self._extract_text(response)
        logger.info('Groq response received: %s', (text or '')[:200])
        return (text or '').strip()

    def _extract_text(self, response: Any) -> str:
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

        return text
