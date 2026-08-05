import json
import logging
import re
from typing import Any, Tuple

logger = logging.getLogger(__name__)


class ResponseValidationError(ValueError):
    """Raised when a provider response cannot be validated as JSON."""


def validate_json_response(raw_response: Any) -> Tuple[bool, Any, str]:
    """Validate a provider response and return (valid, parsed_json, error_message)."""
    candidate = (raw_response or '').strip()

    if not candidate:
        return False, None, 'Response did not contain any content.'

    if isinstance(raw_response, (dict, list)):
        return True, raw_response, ''

    if candidate.startswith('```'):
        candidate = re.sub(r'^```(?:json)?\s*|\s*```$', '', candidate, flags=re.IGNORECASE | re.MULTILINE)

    candidate = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', candidate)
    candidate = candidate.replace('\u0000', '')

    start = candidate.find('{')
    end = candidate.rfind('}')
    if start != -1 and end > start:
        candidate = candidate[start:end + 1]

    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError as exc:
        logger.error('Invalid JSON response: %s', exc)
        return False, None, str(exc)

    if not isinstance(parsed, dict):
        return False, None, 'Response is valid JSON but is not a JSON object.'

    return True, parsed, ''
