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

        Glossary.objects.filter(paper=paper).delete()
        for index, item in enumerate(self.payload['glossary_terms'], start=1):
            Glossary.objects.create(
                paper=paper,
                term=item['term'],
                simple_explanation=item.get('simple_explanation', ''),
                technical_explanation=item.get('technical_explanation', ''),
                example=item.get('example', ''),
                display_order=index,
            )

        Flashcard.objects.filter(paper=paper).delete()
        for index, item in enumerate(self.payload['flashcards'], start=1):
            Flashcard.objects.create(
                paper=paper,
                question=item['question'],
                answer=item['answer'],
                display_order=index,
            )

        QuizQuestion.objects.filter(paper=paper).delete()
        for index, item in enumerate(self.payload['quiz_questions'], start=1):
            QuizQuestion.objects.create(
                paper=paper,
                question=item['question'],
                option_a=item['option_a'],
                option_b=item['option_b'],
                option_c=item['option_c'],
                option_d=item['option_d'],
                correct_answer=item['correct_answer'],
                explanation=item.get('explanation', ''),
                display_order=index,
            )

        VivaQuestion.objects.filter(paper=paper).delete()
        for index, item in enumerate(self.payload['viva_questions'], start=1):
            VivaQuestion.objects.create(
                paper=paper,
                question=item['question'],
                suggested_answer=item.get('suggested_answer', ''),
                follow_up_question=item.get('follow_up_question', ''),
                display_order=index,
            )

        progress, created = LearningProgress.objects.get_or_create(paper=paper)
        progress.overview_completed = True
        progress.beginner_completed = True
        progress.technical_completed = True
        progress.glossary_completed = True
        progress.flashcards_completed = True
        progress.quiz_completed = True
        progress.viva_completed = True
        progress.notes_completed = False
        progress.overall_progress = 100
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

        Glossary.objects.filter(paper=paper).delete()
        for index, item in enumerate(self.payload.get('glossary', []), start=1):
            Glossary.objects.create(
                paper=paper,
                term=item.get('term', ''),
                simple_explanation=item.get('simple_explanation', ''),
                technical_explanation=item.get('technical_explanation', ''),
                example=item.get('example', ''),
                display_order=index,
            )

        Flashcard.objects.filter(paper=paper).delete()
        for index, item in enumerate(self.payload.get('flashcards', []), start=1):
            Flashcard.objects.create(
                paper=paper,
                question=item.get('question', ''),
                answer=item.get('answer', ''),
                display_order=index,
            )

        QuizQuestion.objects.filter(paper=paper).delete()
        for index, item in enumerate(self.payload.get('quiz_questions', []), start=1):
            QuizQuestion.objects.create(
                paper=paper,
                question=item.get('question', ''),
                option_a=item.get('option_a', ''),
                option_b=item.get('option_b', ''),
                option_c=item.get('option_c', ''),
                option_d=item.get('option_d', ''),
                correct_answer=item.get('correct_answer', ''),
                explanation=item.get('explanation', ''),
                display_order=index,
            )

        VivaQuestion.objects.filter(paper=paper).delete()
        for index, item in enumerate(self.payload.get('viva_questions', []), start=1):
            VivaQuestion.objects.create(
                paper=paper,
                question=item.get('question', ''),
                suggested_answer=item.get('suggested_answer', ''),
                follow_up_question=item.get('follow_up_question', ''),
                display_order=index,
            )

        progress, created = LearningProgress.objects.get_or_create(paper=paper)
        progress.overview_completed = True
        progress.beginner_completed = True
        progress.technical_completed = False
        progress.glossary_completed = bool(self.payload.get('glossary'))
        progress.flashcards_completed = bool(self.payload.get('flashcards'))
        progress.quiz_completed = bool(self.payload.get('quiz_questions'))
        progress.viva_completed = bool(self.payload.get('viva_questions'))
        progress.notes_completed = False
        progress.overall_progress = 50
        progress.last_accessed = timezone.now()
        progress.save()

        return analysis