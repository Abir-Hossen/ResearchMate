"""Minimal Gemini connectivity test service.

This is intentionally small and standalone: it only verifies that a configured
API key can be used to call Google's Gemini API via the `google.genai` SDK.
It does not integrate with the learning pipeline or create any persistent
models.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Dict, Any

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

logger = logging.getLogger(__name__)


class GeminiConnectivityService:
    model_name = 'gemini-3.1-flash-lite'

    def __init__(self):
        api_key = getattr(settings, 'GEMINI_API_KEY', None) or os.environ.get('GEMINI_API_KEY')
        if not api_key:
            logger.error('No GEMINI_API_KEY found in settings or environment.')
            raise ImproperlyConfigured('GEMINI_API_KEY is not configured. Create a .env file or set the environment variable.')

        # Do not log the key itself.
        logger.info('Gemini API key detected in environment (not displayed).')

        # Lazy import of the official SDK so the project can still start if it's
        # not installed. The test view will show the exception if missing.
        try:
            import google.genai as gen
        except Exception as exc:  # pragma: no cover - environment-specific
            logger.exception('Failed to import google.genai SDK.')
            raise

        # Initialize the SDK client with the provided key.
        self.client = gen.Client(api_key=api_key)

    def test_connection(self) -> Dict[str, Any]:
        """Send a tiny prompt and return the plain text response and timing.

        Returns a dict with keys: model, response (string), elapsed (seconds).
        Raises errors for missing API key, SDK import issues, or request errors.
        """
        prompt = "Reply with exactly:\nResearchMate Gemini Connected"

        logger.info('Sending Gemini connectivity test request to model %s', self.model_name)
        start = time.perf_counter()

        # Use the SDK model-level generate_content API which returns a rich
        # response object; we extract the first content text result.
        try:
            resp = self.client.models.generate_content(
                model=self.model_name,
                contents=[{'parts': [{'text': prompt}]}],
                config={'responseMimeType': 'text/plain'},
            )
        except Exception:
            logger.exception('Gemini request failed.')
            raise

        elapsed = time.perf_counter() - start
        logger.info('Gemini responded in %.3fs', elapsed)

        # Extract the returned text in a few common shapes.
        text = ''
        try:
            if hasattr(resp, 'candidates') and resp.candidates:
                candidate = resp.candidates[0]
                content = getattr(candidate, 'content', None)
                if content is not None:
                    # content may be a list or a single Content object.
                    if isinstance(content, (list, tuple)):
                        text = content[0].parts[0].text
                    else:
                        text = content.parts[0].text
                else:
                    text = str(resp)
            elif hasattr(resp, 'outputs') and resp.outputs:
                output = resp.outputs[0]
                content = getattr(output, 'content', None)
                if content is not None:
                    if isinstance(content, (list, tuple)):
                        text = content[0].parts[0].text
                    else:
                        text = content.parts[0].text
                else:
                    text = str(resp)
            else:
                text = str(resp)
        except Exception:
            logger.exception('Failed to extract text from Gemini response.')
            text = str(resp)

        text = (text or '').strip()
        logger.info('Gemini raw response: %s', text[:200])

        return {'model': self.model_name, 'response': text, 'elapsed': elapsed}
