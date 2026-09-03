import re

from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone

from .ai_service import AIService
from .models import AIAnalysis
from .provider_factory import ProviderFactory
from .response_validator import validate_json_response


class TechnicalExplanationError(ValueError):
    """Application-level error raised when technical explanation generation fails."""


def _word_count(text):
    return len((text or '').split())


def _clean_extracted_text_for_technical_prompt(extracted_text):
    text = (extracted_text or '').strip()
    if not text:
        return ''

    lines = []
    for line in text.splitlines():
        cleaned = line.strip()
        if not cleaned:
            continue
        if re.fullmatch(r'\d+', cleaned):
            continue
        if re.fullmatch(r'Page\s*\d+', cleaned, flags=re.IGNORECASE):
            continue
        if cleaned.startswith('http') or cleaned.startswith('www.'):
            continue
        if any(marker in cleaned.lower() for marker in (
            'correspondence', 'author', 'affiliation', 'copyright', 'all rights reserved',
            'journal', 'doi', 'volume', 'issue', 'pages', 'page number', 'conference'
        )):
            continue
        if cleaned.lower().startswith('abstract'):
            continue
        lines.append(cleaned)

    cleaned_text = '\n'.join(lines)
    cleaned_text = re.sub(r'\n{3,}', '\n\n', cleaned_text)
    return cleaned_text


def _is_stale_technical_explanation(text):
    cleaned = (text or '').strip()
    if not cleaned:
        return True

    if cleaned.lower() in {'a technical explanation of the paper.', 'technical explanation'}:
        return True

    word_count = _word_count(cleaned)
    # Match the fresh-generation range so cached explanations are not treated
    # differently from newly generated ones.
    if word_count < 450 or word_count > 850:
        return True

    return False


def _extract_sentences(extracted_text):
    text = (extracted_text or '').strip()
    if not text:
        return []

    sentence_pattern = re.compile(r'[^.!?]+[.!?]?', re.MULTILINE)
    sentences = [match.group(0).strip() for match in sentence_pattern.finditer(text) if match.group(0).strip()]
    return [sentence for sentence in sentences if sentence]


def _build_fallback_technical_explanation(extracted_text):
    content = """# Technical Explanation

## Overall Technical Architecture
The proposed system follows a single end-to-end pipeline that begins with raw paper content and ends with a structured technical prediction or decision. The design is organized so that input data is prepared, transformed into a representation that the model can use, and then passed through the model to produce a final outcome. This architecture is appropriate because it keeps the preprocessing, representation learning, and prediction stages consistent with one another instead of treating them as unrelated steps.

## Model Architecture
The model is selected to match the nature of the task and the kind of signal present in the data. In this paper, the model is used not simply as a black box but as the central mechanism for extracting meaningful structure from the input. Its role is to learn a representation that supports the final prediction, and its interaction with the rest of the pipeline is crucial because every upstream preprocessing decision influences what the model can learn.

## Data Processing Pipeline
The input data is first cleaned and normalized so that the downstream model receives a consistent representation. Features are then extracted or engineered to preserve the information that is most relevant to the task. After that, the model is trained on the processed data and used to generate predictions. This flow reflects the paper's engineering choices: the authors align the data preparation stage with the representation needs of the model so that training is more stable and the results are easier to interpret.

## Technical Design Decisions
The system design emphasizes a practical balance between model capability and interpretability. The researchers chose an architecture that fits the data modality and the prediction objective rather than adopting a generic pattern. In practice, this means the model is designed to leverage the most informative features while keeping the processing flow simple enough to validate. The trade-off is that the chosen design may be less flexible than a more complex alternative, but it is better aligned with the evidence and constraints reported in the paper.

## Experimental Design
The dataset is used to evaluate whether the proposed architecture can solve the target task under realistic conditions. The training procedure is designed to test the effect of the architecture on performance, while the chosen metrics measure whether the system produces useful predictions rather than only a superficially plausible output. Comparison methods are included to show whether the proposed design offers a genuine advantage over simpler or more standard baselines.

## Technical Strengths
- The pipeline is coherent from input preparation to final prediction.
- The architecture is shaped around the data and task rather than being unnecessarily complex.
- The model and preprocessing stages are tightly coupled, which helps explain the system behavior.
- The experimental comparison provides evidence for the value of the selected design.

## Technical Limitations
- The paper does not provide sufficient information about this aspect.
- The architecture may be limited by the scale or characteristics of the dataset.
- The reported design decisions are constrained by the evaluation setup described in the paper.

## Engineering Takeaways
The main lesson for an AI engineer is that a strong technical system is not defined only by the model itself, but by how well the data pipeline, model choice, and evaluation strategy work together. The paper's contribution lies in making these decisions coherent and task-specific rather than simply using a popular architecture.
"""

    return content.strip()


def _clean_technical_markdown(raw_response):
    valid, payload, error_message = validate_json_response(raw_response)
    if not valid:
        raise TechnicalExplanationError(f'AI returned an invalid technical explanation response: {error_message}')

    if not isinstance(payload, dict):
        raise TechnicalExplanationError('AI returned an invalid technical explanation response format.')

    technical_explanation = payload.get('technical_explanation')
    if not isinstance(technical_explanation, str) or not technical_explanation.strip():
        raise TechnicalExplanationError('AI response did not include a usable technical explanation.')

    cleaned = technical_explanation.strip()
    word_count = _word_count(cleaned)
    # Prompt requests roughly 500-700 words; allow ~10% tolerance on each side
    # to avoid rejecting valid paper-specific output that is naturally slightly
    # shorter or longer. Still guard against empty, trivially short, or runaway
    # responses.
    if word_count < 450 or word_count > 850:
        return None

    return cleaned


def generate_technical_explanation(paper, force_refresh=False):
    """Generate a technical explanation from the stored PaperContent and persist it once."""
    try:
        content = paper.content
    except ObjectDoesNotExist as exc:
        raise TechnicalExplanationError('Paper content must exist before generating a technical explanation.') from exc

    if not content.extracted_text or not content.extracted_text.strip():
        raise TechnicalExplanationError('Paper content must contain extracted text before generating a technical explanation.')

    analysis, _ = AIAnalysis.objects.get_or_create(paper=paper)
    if not force_refresh and analysis.technical_explanation and analysis.technical_explanation.strip() and not _is_stale_technical_explanation(analysis.technical_explanation):
        return analysis.technical_explanation

    analysis.analysis_status = 'Processing'
    analysis.analysis_error = ''
    analysis.raw_response = ''
    analysis.last_updated = timezone.now()
    analysis.save(update_fields=['analysis_status', 'analysis_error', 'raw_response', 'last_updated'])

    provider = None
    ai_service = None
    technical_explanation = None
    last_error = None

    try:
        provider = ProviderFactory.create_provider()
        ai_service = AIService(provider=provider)
    except Exception as exc:
        raise TechnicalExplanationError('Technical explanation generation failed. Please try again later.') from exc

    cleaned_text = _clean_extracted_text_for_technical_prompt(content.extracted_text)

    for attempt in range(2):
        try:
            raw_response = ai_service.generate_feature('technical', cleaned_text)
            technical_explanation = _clean_technical_markdown(raw_response)
            if technical_explanation is not None:
                break
            raise TechnicalExplanationError('Technical explanation length was outside the accepted paper-specific range.')
        except TechnicalExplanationError as exc:
            last_error = exc
            if attempt == 0:
                analysis.analysis_status = 'Processing'
                analysis.analysis_error = str(exc)
                analysis.last_updated = timezone.now()
                analysis.save(update_fields=['analysis_status', 'analysis_error', 'last_updated'])
                continue
            break
        except Exception as exc:
            last_error = TechnicalExplanationError('Technical explanation generation failed. Please try again later.')
            if attempt == 0:
                analysis.analysis_status = 'Processing'
                analysis.analysis_error = str(last_error)
                analysis.last_updated = timezone.now()
                analysis.save(update_fields=['analysis_status', 'analysis_error', 'last_updated'])
                continue
            break

    if technical_explanation is None:
        analysis.analysis_status = 'Failed'
        analysis.analysis_error = str(last_error or 'Technical explanation generation failed. Please try again later.')
        analysis.last_updated = timezone.now()
        analysis.save(update_fields=['analysis_status', 'analysis_error', 'last_updated'])
        raise TechnicalExplanationError(str(last_error or 'Technical explanation generation failed. Please try again later.'))

    analysis.technical_explanation = technical_explanation
    analysis.analysis_status = 'Ready'
    analysis.analysis_error = ''
    analysis.ai_model = getattr(provider, 'model_name', None) or analysis.ai_model or 'groq'
    analysis.generated_at = analysis.generated_at or timezone.now()
    analysis.last_updated = timezone.now()
    analysis.save(update_fields=['technical_explanation', 'analysis_status', 'analysis_error', 'ai_model', 'generated_at', 'last_updated'])
    return technical_explanation
