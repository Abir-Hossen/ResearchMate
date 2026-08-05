import json
import logging
import re
import time
from io import BytesIO

from django.core.exceptions import ObjectDoesNotExist
from django.shortcuts import get_object_or_404
from django.utils import timezone

try:
    import fitz
except ImportError:  # pragma: no cover - environment fallback
    fitz = None

from .ai_service import AIService
from .groq_connectivity import GroqLearningService as BaseGroqLearningService
from .provider_factory import ProviderFactory
from .models import AIAnalysis, Paper, PaperContent
from .parser import GroqPayloadParser, MockPayloadParser
from .response_validator import validate_json_response

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class GroqLearningService(BaseGroqLearningService):
    """Compatibility wrapper that exposes the generic provider-style generate method."""

    def generate(self, prompt):
        return self.generate_analysis(prompt)


def get_user_paper(user, paper_id):
    return get_object_or_404(Paper, pk=paper_id, owner=user)


def _get_user_facing_error_message(analysis):
    if analysis is None:
        return 'AI analysis could not be completed. Please try again later.'

    analysis_error = getattr(analysis, 'analysis_error', None)
    if not analysis_error and hasattr(analysis, 'analysis') and getattr(analysis.analysis, 'analysis_error', None):
        analysis_error = analysis.analysis.analysis_error

    error_text = (analysis_error or '').strip().lower()
    auth_markers = ('authentication', 'api configuration', 'api key', 'invalid key', 'unauthorized', 'forbidden', 'credentials')
    connection_markers = ('connect', 'connection', 'network', 'timed out', 'timeout', 'dns')
    explicit_limit_markers = (
        '[rate_limit]',
        'rate limit exceeded',
        'rate-limit exceeded',
        'usage limit exceeded',
        'quota exceeded',
        'exceeded your current quota',
        'too many requests',
        '429',
    )

    if any(marker in error_text for marker in auth_markers):
        return 'AI analysis could not be completed. Authentication with the AI provider failed. Please check the API configuration.'
    if any(marker in error_text for marker in connection_markers):
        return 'AI analysis could not be completed. Unable to connect to the AI provider. Please check your internet connection and try again.'
    if any(marker in error_text for marker in explicit_limit_markers):
        return 'AI analysis could not be completed because the configured AI provider has reached its usage limit. Please try again later or switch to another configured provider.'
    return 'AI analysis could not be completed. Please try again later.'


def get_paper_metadata(paper):
    try:
        analysis = paper.ai_analysis
    except ObjectDoesNotExist:
        analysis = None

    status = paper.processing_status
    if analysis is not None and analysis.analysis_status == 'Failed':
        status = 'Failed'

    return {
        'paper': paper,
        'title': paper.title,
        'uploaded_at': paper.uploaded_at,
        'status': status,
        'content_status': paper.content_status,
        'file_name': paper.pdf_file.name.split('/')[-1],
        'file_size': paper.pdf_file.size,
        'is_prepared': paper.content_status == 'Ready',
    }


def build_workspace_context(user, paper_id, active_tab):
    paper = get_user_paper(user, paper_id)

    try:
        analysis = paper.ai_analysis
    except ObjectDoesNotExist:
        analysis = None

    try:
        progress = paper.learning_progress
    except ObjectDoesNotExist:
        progress = None

    glossary_terms = []
    flashcards = []
    quiz_questions = []
    viva_questions = []
    analysis_contributions = []

    if analysis is not None:
        analysis_contributions = [item for item in analysis.key_contributions.splitlines() if item.strip()] if analysis.key_contributions else []

    try:
        glossary_terms = list(paper.glossary_terms.all().order_by('display_order', 'id'))
        flashcards = list(paper.flashcards.all().order_by('display_order', 'id'))
        quiz_questions = list(paper.quiz_questions.all().order_by('display_order', 'id'))
        viva_questions = list(paper.viva_questions.all().order_by('display_order', 'id'))
    except ObjectDoesNotExist:
        pass

    return {
        'paper': paper,
        'active_tab': active_tab,
        'analysis': analysis,
        'can_retry_generation': bool(analysis is not None and analysis.analysis_status == 'Failed'),
        'user_facing_error_message': _get_user_facing_error_message(analysis),
        'progress': progress,
        'glossary_terms': glossary_terms,
        'flashcards': flashcards,
        'quiz_questions': quiz_questions,
        'viva_questions': viva_questions,
        'analysis_contributions': analysis_contributions,
    }


def extract_pdf_content(paper):
    paper.processing_status = 'Processing'
    paper.save(update_fields=['processing_status'])

    content, created = PaperContent.objects.get_or_create(paper=paper)
    content.extraction_status = 'Processing'
    content.save(update_fields=['extraction_status'])

    try:
        with paper.pdf_file.open('rb') as pdf_handle:
            pdf_bytes = pdf_handle.read()
    except Exception:
        content.extraction_status = 'Failed'
        content.save(update_fields=['extraction_status'])
        paper.processing_status = 'Uploaded'
        paper.save(update_fields=['processing_status'])
        raise

    try:
        if fitz is not None:
            document = fitz.open(stream=pdf_bytes, filetype='pdf')
            extracted_text = '\n\n'.join(page.get_text() for page in document)
            page_count = document.page_count
            document.close()
        else:
            from pypdf import PdfReader

            reader = PdfReader(BytesIO(pdf_bytes))
            extracted_text = '\n\n'.join((page.extract_text() or '').strip() for page in reader.pages)
            page_count = len(reader.pages)

        content.extracted_text = extracted_text.strip()
        content.page_count = page_count
        content.extraction_status = 'Ready'
        content.extracted_at = timezone.now()
        content.save()
        paper.processing_status = 'Completed'
        paper.save(update_fields=['processing_status'])
        return content
    except Exception:
        content.extraction_status = 'Failed'
        content.save(update_fields=['extraction_status'])
        paper.processing_status = 'Uploaded'
        paper.save(update_fields=['processing_status'])
        raise


def _persist_failure(paper, raw_response, exc, provider=None, model_name=None, prompt_length=None, response_time=None, token_usage=None):
    try:
        analysis = paper.ai_analysis
    except ObjectDoesNotExist:
        analysis = None

    provider_name = type(provider).__name__ if provider is not None else 'unknown'
    error_details = {}
    if provider is not None and hasattr(provider, 'get_error_details'):
        error_details = provider.get_error_details(exc) or {}

    error_type = error_details.get('error_type', 'PROVIDER_ERROR')
    readable_error = error_details.get('message') or str(exc) or type(exc).__name__
    retry_recommendation = error_details.get('retry_recommendation') or 'Please try again later.'

    if error_type == 'RATE_LIMIT':
        error_message = f"[RATE_LIMIT] {readable_error} Retry: {retry_recommendation}"
    else:
        error_message = readable_error

    context_parts = []
    if provider_name != 'unknown':
        context_parts.append(f'provider={provider_name}')
    if model_name:
        context_parts.append(f'model={model_name}')
    if prompt_length is not None:
        context_parts.append(f'prompt_length={prompt_length}')
    if response_time is not None:
        context_parts.append(f'response_time={response_time:.3f}s')
    if token_usage:
        context_parts.append(f'token_usage={token_usage}')

    if context_parts:
        error_message = f'{error_message} ({"; ".join(context_parts)})'

    if analysis is not None and any([
        analysis.overview,
        analysis.beginner_explanation,
        analysis.technical_explanation,
        analysis.key_contributions,
        analysis.key_concepts,
    ]):
        analysis.analysis_status = 'Failed'
        analysis.ai_model = model_name or getattr(provider, 'model_name', None) or 'groq'
        analysis.analysis_error = error_message
        analysis.raw_response = raw_response
        analysis.last_updated = timezone.now()
        analysis.save(update_fields=['analysis_status', 'ai_model', 'analysis_error', 'raw_response', 'last_updated'])
        return analysis

    analysis, created = AIAnalysis.objects.get_or_create(paper=paper)
    analysis.analysis_status = 'Failed'
    analysis.ai_model = model_name or getattr(provider, 'model_name', None) or 'groq'
    analysis.analysis_error = error_message
    analysis.raw_response = raw_response
    analysis.generated_at = timezone.now()
    analysis.last_updated = timezone.now()
    analysis.save(update_fields=['analysis_status', 'ai_model', 'analysis_error', 'raw_response', 'generated_at', 'last_updated'])
    return analysis


def _parse_json_payload(raw_response):
    valid, parsed, error_message = validate_json_response(raw_response)
    if not valid:
        raise ValueError(error_message)
    return parsed


def process_mock_ai(paper):
    logger.info('[StartLearning] Paper=%s begin', paper.id)

    provider = None
    provider_name = None
    model_name = None
    prompt_length = None
    response_time = None
    token_usage = None
    raw_response = ''
    analysis = None

    try:
        content = paper.content
        logger.info('[Step 1] Paper=%s PaperContent loaded', paper.id)
    except ObjectDoesNotExist:
        content = None
        logger.exception('[Step 1] Paper=%s PaperContent lookup failed', paper.id)

    if content is None or not content.extracted_text:
        logger.error('[Step 1] Paper=%s PaperContent missing or empty text', paper.id)
        error_message = 'Paper content must exist and contain extracted text before AI processing.'
        analysis, _ = AIAnalysis.objects.get_or_create(paper=paper)
        _persist_failure(paper, raw_response, ValueError(error_message))
        return analysis

    logger.info('[Step 1] Paper=%s extracted_text length=%s', paper.id, len(content.extracted_text))

    try:
        analysis, created = AIAnalysis.objects.get_or_create(paper=paper)
        analysis.analysis_status = 'Processing'
        analysis.analysis_error = ''
        analysis.raw_response = ''
        analysis.last_updated = timezone.now()
        analysis.save(update_fields=['analysis_status', 'analysis_error', 'raw_response', 'last_updated'])
        logger.info('[Step 3] Paper=%s AIAnalysis ready (created=%s)', paper.id, created)
    except Exception as exc:
        logger.exception('[Step 3] Paper=%s failed to create/update AIAnalysis', paper.id)
        _persist_failure(paper, raw_response, exc)
        return analysis

    logger.info('[Step 2] Paper=%s prompt build will start', paper.id)

    try:
        provider = ProviderFactory.create_provider()
        provider_name = type(provider).__name__
        logger.info('[Step 5] Paper=%s provider selected: %s', paper.id, provider_name)
        model_name = getattr(provider, 'model_name', None)
        if model_name:
            logger.info('[Step 5] Paper=%s selected model: %s', paper.id, model_name)
    except Exception as exc:
        logger.exception('[Step 5] Paper=%s provider selection failed', paper.id)
        _persist_failure(paper, raw_response, exc, provider=provider, model_name=model_name, prompt_length=prompt_length, response_time=response_time, token_usage=token_usage)
        return analysis

    try:
        ai_service = AIService(provider=provider)
        logger.info('[Step 4] Paper=%s building prompt', paper.id)
        prompt = ai_service.build_prompt('beginner', content.extracted_text)
        prompt_length = len(prompt or '')
        logger.info('[Step 4] Paper=%s prompt built (length=%s)', paper.id, prompt_length)
    except Exception as exc:
        logger.exception('[Step 4] Paper=%s prompt build failed', paper.id)
        _persist_failure(paper, raw_response, exc, provider=provider, model_name=model_name, prompt_length=prompt_length, response_time=response_time, token_usage=token_usage)
        return analysis

    try:
        logger.info('[Step 6] Paper=%s sending request to provider', paper.id)
        start_time = time.perf_counter()
        raw_response = ai_service.generate_feature('beginner', content.extracted_text)
        response_time = time.perf_counter() - start_time
        token_usage = provider.get_usage_summary(getattr(provider, 'last_usage', None)) if provider is not None and hasattr(provider, 'get_usage_summary') else None
        logger.info('[Step 6] Paper=%s response received (length=%s)', paper.id, len(raw_response or ''))
        logger.info('[Step 6] Paper=%s raw_response_type=%s', paper.id, type(raw_response).__name__)
        logger.info('[Step 6] Paper=%s provider=%s model=%s prompt_length=%s response_time=%.3fs token_usage=%s', paper.id, provider_name, model_name, prompt_length, response_time, token_usage or 'n/a')
        logger.info('[Step 6] Paper=%s raw_response_text=%s', paper.id, raw_response)
    except Exception as exc:
        logger.exception('[Step 6] Paper=%s provider request failed', paper.id)
        _persist_failure(paper, raw_response, exc, provider=provider, model_name=model_name, prompt_length=prompt_length, response_time=response_time, token_usage=token_usage)
        return analysis

    try:
        logger.info('[Step 7] Paper=%s parsing response', paper.id)
        valid, payload, error_message = validate_json_response(raw_response)
        logger.info('[Step 7] Paper=%s validation_result=%s', paper.id, 'valid' if valid else 'invalid')
        logger.info('[Step 7] Paper=%s validation_error=%s', paper.id, error_message or 'None')
        if not valid:
            raise ValueError(error_message)
        logger.info('[Step 7] Paper=%s parsed payload keys=%s', paper.id, sorted(payload.keys()) if isinstance(payload, dict) else type(payload).__name__)
    except Exception as exc:
        logger.exception('[Step 7] Paper=%s response parsing failed', paper.id)
        _persist_failure(paper, raw_response, exc, provider=provider, model_name=model_name, prompt_length=prompt_length, response_time=response_time, token_usage=token_usage)
        return analysis

    try:
        logger.info('[Step 8] Paper=%s saving AIAnalysis', paper.id)
        parser = GroqPayloadParser(payload)
        result = parser.create_models(paper, raw_response=raw_response, analysis_status='Ready')
        logger.info('[Step 8] Paper=%s AIAnalysis saved', paper.id)
        return result
    except Exception as exc:
        logger.exception('[Step 8] Paper=%s saving AIAnalysis or derived models failed', paper.id)
        _persist_failure(paper, raw_response, exc, provider=provider, model_name=model_name, prompt_length=prompt_length, response_time=response_time, token_usage=token_usage)
        return analysis
