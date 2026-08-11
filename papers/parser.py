"""Parser utilities for AI payloads produced by the learning pipeline."""

from django.utils import timezone

from .models import AIAnalysis, Flashcard, Glossary, LearningProgress, QuizQuestion, VivaQuestion


class MockPayloadParser:
    """Validate and save a mock AI payload into the database."""

    required_fields = {
        'overview',
        'beginner_explanation',
        'technical_explanation',
        'key_contributions',
        'key_concepts',
        'reading_difficulty',
        'glossary_terms',
        'flashcards',
        'quiz_questions',
        'viva_questions',
        'metadata',
    }

    def __init__(self, payload):
        self.payload = payload

    def validate(self):
        if not isinstance(self.payload, dict):
            raise ValueError('Mock payload must be a dictionary.')

        missing = self.required_fields.difference(self.payload)
        if missing:
            raise ValueError(f'Missing required payload fields: {sorted(missing)}')

        return True

    def create_models(self, paper):
        self.validate()

        analysis, created = AIAnalysis.objects.get_or_create(paper=paper)
        analysis.overview = self.payload['overview']
        analysis.beginner_explanation = self.payload['beginner_explanation']
        analysis.technical_explanation = self.payload['technical_explanation']
        analysis.key_contributions = '\n'.join(self.payload['key_contributions'])
        analysis.key_concepts = self.payload['key_concepts']
        analysis.reading_difficulty_level = self.payload['reading_difficulty']['level']
        analysis.reading_difficulty_reason = self.payload['reading_difficulty']['reason']
        analysis.analysis_status = 'Ready'
        analysis.ai_model = 'mock-learning-service'
        analysis.generated_at = timezone.now()
        analysis.save()

        progress, created = LearningProgress.objects.get_or_create(paper=paper)
        progress.overview_completed = True
        progress.beginner_completed = True
        progress.technical_completed = False
        progress.glossary_completed = False
        progress.flashcards_completed = False
        progress.quiz_completed = False
        progress.viva_completed = False
        progress.notes_completed = False
        progress.overall_progress = 25
        progress.last_accessed = timezone.now()
        progress.save()

        return analysis


class GroqPayloadParser:
    """Parse a Groq-generated JSON payload into the database models."""

    required_fields = {
        'beginner_explanation',
        'key_contributions',
        'key_concepts',
        'reading_difficulty',
    }

    def __init__(self, payload):
        self.payload = payload

    def validate(self):
        if not isinstance(self.payload, dict):
            raise ValueError('Groq payload must be a dictionary.')

        missing = self.required_fields.difference(self.payload)
        if missing:
            raise ValueError(f'Missing required payload fields: {sorted(missing)}')

        return True

    def create_models(self, paper, analysis_status='Ready', ai_model='groq', raw_response='', analysis_error=''):
        self.validate()

        analysis, created = AIAnalysis.objects.get_or_create(paper=paper)
        analysis.overview = self.payload.get('beginner_explanation', '')
        analysis.beginner_explanation = self.payload.get('beginner_explanation', '')
        analysis.technical_explanation = ''
        analysis.key_contributions = '\n'.join(self.payload.get('key_contributions', []))
        analysis.key_concepts = self.payload.get('key_concepts', [])

        reading_difficulty = self.payload.get('reading_difficulty', {})
        if isinstance(reading_difficulty, dict):
            analysis.reading_difficulty_level = reading_difficulty.get('level', '')
            analysis.reading_difficulty_reason = reading_difficulty.get('reason', '')
        else:
            analysis.reading_difficulty_level = str(reading_difficulty or '')
            analysis.reading_difficulty_reason = ''

        analysis.analysis_status = analysis_status
        analysis.ai_model = ai_model
        analysis.raw_response = raw_response
        analysis.analysis_error = analysis_error
        analysis.generated_at = timezone.now()
        analysis.save()

        if analysis_status != 'Ready':
            return analysis

        progress, created = LearningProgress.objects.get_or_create(paper=paper)
        progress.overview_completed = True
        progress.beginner_completed = True
        progress.technical_completed = False
        progress.glossary_completed = False
        progress.flashcards_completed = False
        progress.quiz_completed = False
        progress.viva_completed = False
        progress.notes_completed = False
        progress.overall_progress = 25
        progress.last_accessed = timezone.now()
        progress.save()

        return analysis