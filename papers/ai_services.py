"""Simple mock AI service used for local development and tests.

Provides `MockLearningService.build_payload()` which returns a minimal
payload shape compatible with `MockPayloadParser`.
"""

from __future__ import annotations

from typing import Dict, Any


class MockLearningService:
    """Generate a deterministic mock payload from extracted text.

    This avoids external network calls when running the dev server or tests
    that don't require an external AI provider.
    """

    def __init__(self, extracted_text: str):
        self.extracted_text = (extracted_text or '').strip()

    def build_payload(self) -> Dict[str, Any]:
        if not self.extracted_text:
            raise ValueError('Extracted text is required for mock analysis.')

        # Keep the mock content small but valid for the parser.
        overview = self.extracted_text[:400] + ("..." if len(self.extracted_text) > 400 else "")
        beginner = f"Beginner summary: {overview[:200]}"
        technical = f"Technical summary: {overview[:200]}"

        payload = {
            'overview': overview,
            'beginner_explanation': beginner,
            'technical_explanation': technical,
            'key_contributions': ['Auto-generated highlight 1'],
            'key_concepts': [
                {'term': 'AutoConcept', 'explanation': 'An auto-generated concept explanation.'}
            ],
            'reading_difficulty': {'level': 'Intermediate', 'reason': 'Mocked difficulty.'},
            'glossary_terms': [
                {
                    'term': 'ResearchMate',
                    'simple_explanation': 'A study platform for research papers.',
                    'technical_explanation': 'A mock glossary entry used for local testing.',
                    'example': 'ResearchMate helps structure learning materials.',
                }
            ],
            'flashcards': [
                {
                    'question': 'What does ResearchMate help with?',
                    'answer': 'It helps structure learning material from research papers.',
                }
            ],
            'quiz_questions': [
                {
                    'question': 'What is the purpose of ResearchMate?',
                    'option_a': 'To edit PDFs',
                    'option_b': 'To help study research papers',
                    'option_c': 'To manage email',
                    'option_d': 'To create databases',
                    'correct_answer': 'B',
                    'explanation': 'ResearchMate structures learning materials from papers.',
                }
            ],
            'viva_questions': [
                {
                    'question': 'How does ResearchMate support learning?',
                    'suggested_answer': 'It converts uploaded papers into structured study content.',
                    'follow_up_question': 'What kind of content does it create?',
                }
            ],
            'metadata': {'source': 'mock'},
        }

        return payload
