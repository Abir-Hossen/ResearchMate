from __future__ import annotations

from .provider_factory import ProviderFactory
from .prompt_manager import (
    get_beginner_prompt,
    get_difficulty_prompt,
    get_flashcards_prompt,
    get_glossary_prompt,
    get_quiz_prompt,
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

    def build_prompt(self, feature_name, extracted_text, prompt_type='default', section_title=None):
        prompt_builder = {
            'beginner': get_beginner_prompt,
            'technical': get_technical_prompt,
            'glossary': get_glossary_prompt,
            'section_learning': get_section_learning_prompt,
            'flashcards': get_flashcards_prompt,
            'viva': get_viva_prompt,
            'quiz': get_quiz_prompt,
            'difficulty': get_difficulty_prompt,
        }.get(feature_name)

        if prompt_builder is None:
            raise ValueError(f'Unsupported feature: {feature_name}')

        if feature_name == 'section_learning' and prompt_type == 'section_detection':
            return get_section_detection_prompt(extracted_text)

        if feature_name == 'section_learning' and prompt_type == 'section_explanation':
            return get_single_section_explanation_prompt(section_title or 'Section', extracted_text)

        return prompt_builder(extracted_text)

    def generate_feature(self, feature_name, extracted_text, prompt_type='default', section_title=None):
        prompt = self.build_prompt(feature_name, extracted_text, prompt_type=prompt_type, section_title=section_title)
        return self.provider.generate(prompt)
