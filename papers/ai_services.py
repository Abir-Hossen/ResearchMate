"""Mock AI orchestration service for the Learning Hub.

This module is intentionally self-contained and does not call any external API.
It returns structured mock learning data that mirrors the shape expected for
future Gemini integration.
"""

import hashlib
import re
from datetime import datetime

from django.utils import timezone


class MockLearningService:
    """Create realistic mock learning content from extracted paper text."""

    def __init__(self, extracted_text):
        self.extracted_text = extracted_text or ''

    def build_payload(self):
        if not self.extracted_text:
            raise ValueError('Extracted text is required for mock learning generation.')

        text = re.sub(r'\s+', ' ', self.extracted_text).strip()
        words = text.split()
        preview = ' '.join(words[:60])
        title_words = [word for word in words if word.isalpha()][:8]
        base_topic = ' '.join(title_words) or 'research topic'
        topic_name = base_topic.title()
        digest = hashlib.sha256(text.encode('utf-8')).hexdigest()[:10]

        return {
            'overview': f'{topic_name} is introduced as a practical research topic with strong educational relevance. The mock analysis highlights the core ideas, the main contribution, and the most useful study angles for learners.',
            'beginner_explanation': f'In simple terms, {topic_name} is presented as a structured concept that can be understood by first-time readers through clear examples and careful explanations.',
            'technical_explanation': f'Technically, {topic_name} involves layered reasoning, methodical decomposition, and evidence-based interpretation that connects the main ideas to the broader research context.',
            'key_contributions': [
                'Clarifies the central problem being addressed.',
                'Connects core concepts to practical application.',
                'Provides a study-friendly structure for future review.',
            ],
            'key_concepts': [
                {'term': 'Research framing', 'explanation': 'Defining the problem clearly before analysis.'},
                {'term': 'Methodological reasoning', 'explanation': 'Explaining how the study approaches the topic.'},
                {'term': 'Evidence synthesis', 'explanation': 'Connecting claims to supporting ideas.'},
            ],
            'reading_difficulty': {
                'level': 'Intermediate',
                'reason': 'The material combines conceptual explanations with technical details that require careful review.',
            },
            'glossary_terms': [
                {
                    'term': 'Framework',
                    'simple_explanation': 'A structured way of organizing ideas.',
                    'technical_explanation': 'A conceptual model used to interpret a problem or system.',
                    'example': 'A framework for comparing two research methods.',
                    'display_order': 1,
                },
                {
                    'term': 'Evidence',
                    'simple_explanation': 'The information that supports a claim.',
                    'technical_explanation': 'Observations, data, or references used to justify an argument.',
                    'example': 'Evidence from prior studies strengthens the conclusion.',
                    'display_order': 2,
                },
            ],
            'flashcards': [
                {
                    'question': f'What is the main purpose of {topic_name}?',
                    'answer': 'To explain the topic clearly and support structured learning.',
                    'display_order': 1,
                },
                {
                    'question': f'How does {topic_name} support academic understanding?',
                    'answer': 'It helps learners connect evidence, structure, and interpretation.',
                    'display_order': 2,
                },
            ],
            'quiz_questions': [
                {
                    'question': f'Which statement best describes {topic_name}?',
                    'option_a': 'A purely decorative concept',
                    'option_b': 'A structured research idea with educational value',
                    'option_c': 'A mathematical formula only',
                    'option_d': 'A software installation step',
                    'correct_answer': 'option_b',
                    'explanation': 'The topic is presented as a meaningful academic concept.',
                    'display_order': 1,
                }
            ],
            'viva_questions': [
                {
                    'question': f'How would you explain {topic_name} in a short presentation?',
                    'suggested_answer': 'I would summarize the main idea, its relevance, and its practical significance.',
                    'follow_up_question': 'How would you connect this topic to your broader research interests?',
                    'display_order': 1,
                }
            ],
            'metadata': {
                'preview': preview,
                'topic_name': topic_name,
                'digest': digest,
                'generated_at': timezone.now().isoformat(),
            },
        }