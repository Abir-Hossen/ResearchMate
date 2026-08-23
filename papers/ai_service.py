from __future__ import annotations

from .provider_factory import ProviderFactory
from .prompt_manager import (
    get_beginner_prompt,
    get_difficulty_prompt,
    get_flashcards_prompt,
    get_glossary_prompt,
    get_quiz_prompt,
    get_revision_notes_prompt,
    get_section_learning_prompt,
    get_section_detection_prompt,
    get_single_section_explanation_prompt,
    get_technical_prompt,
    get_viva_prompt,
)


class AIService:
    """Orchestrates prompt selection and provider execution for AI features."""

    def __init__(self, provider=None):
        self.provider = provider or ProviderFactory.create_provider()

    def build_prompt(self, feature_name, extracted_text, prompt_type='default', section_title=None, **kwargs):
        prompt_builder = {
            'beginner': get_beginner_prompt,
            'technical': get_technical_prompt,
            'glossary': get_glossary_prompt,
            'section_learning': get_section_learning_prompt,
            'flashcards': get_flashcards_prompt,
            'viva': get_viva_prompt,
            'quiz': get_quiz_prompt,
            'difficulty': get_difficulty_prompt,
            'revision_notes': get_revision_notes_prompt,
        }.get(feature_name)

        if prompt_builder is None:
            raise ValueError(f'Unsupported feature: {feature_name}')

        if feature_name == 'section_learning' and prompt_type == 'section_detection':
            return get_section_detection_prompt(extracted_text)

        if feature_name == 'section_learning' and prompt_type == 'section_explanation':
            paper_context = kwargs.get('paper_context')
            return get_single_section_explanation_prompt(section_title or 'Section', extracted_text, paper_context=paper_context)

        return prompt_builder(extracted_text)

    def generate_feature(self, feature_name, extracted_text, prompt_type='default', section_title=None, max_completion_tokens=None, **kwargs):
        prompt = self.build_prompt(feature_name, extracted_text, prompt_type=prompt_type, section_title=section_title)
        # Use lower completion limit for section learning to minimize token usage
        if feature_name == 'section_learning' and max_completion_tokens is None:
            max_completion_tokens = 4000
        if feature_name == 'beginner' and max_completion_tokens is None:
            max_completion_tokens = 1500
        # Only pass max_completion_tokens if it's not None
        if max_completion_tokens is not None:
            return self.provider.generate(prompt, max_completion_tokens=max_completion_tokens)
        return self.provider.generate(prompt)
