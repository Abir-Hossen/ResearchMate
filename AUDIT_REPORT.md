================================================================================
RESEARCHMATE AI ARCHITECTURE AUDIT — COMPREHENSIVE REPORT
================================================================================

READ-ONLY AUDIT COMPLETED: 2026-08-17
No modifications made to any project files.

================================================================================
A. CURRENT AI ARCHITECTURE OVERVIEW
================================================================================

ResearchMate uses a modular AI architecture with the following components:

1. CONFIGURATION LAYER
   - Django settings load GROQ_API_KEY, GROQ_MODEL, AI_PROVIDER from .env file
   - Fallback values provided in code if .env not available
   
2. PROVIDER LAYER
   - ProviderFactory: Instantiates the appropriate provider (Groq, Mock, or others)
   - GroqProvider: Wraps Groq SDK client and manages model configuration
   - GroqLearningService: Alternative Groq service (compatibility wrapper)
   
3. SERVICE LAYER
   - AIService: Orchestrates prompt building and provider execution
   - Feature-specific services: glossary, flashcards, quiz, viva, etc.
   
4. PERSISTENCE LAYER
   - AIAnalysis, Glossary, Flashcard, QuizQuestion, VivaQuestion models
   - LearningProgress tracking

================================================================================
B. CONFIGURATION FLOW
================================================================================

SOURCE OF TRUTH FOR CONFIGURATION:
→ Primary: .env file (if present)
→ Fallback: Environment variables
→ Last resort: Hard-coded defaults

LOADING SEQUENCE (ResearchMate/settings.py):

1. load_env_file() is called early in settings module
   - File: .env (absolute path from BASE_DIR)
   - Loads GROQ_API_KEY, GROQ_MODEL, AI_PROVIDER into os.environ
   - If .env doesn't exist, falls back to refresh_settings_from_env()

2. refresh_settings_from_env() called AFTER load_env_file()
   - Sets global module variables:
     * GROQ_API_KEY = os.environ.get('GROQ_API_KEY')
     * GROQ_MODEL = os.environ.get('GROQ_MODEL', 'llama-3.3-70b-versatile')  [HARD-CODED DEFAULT]
     * AI_PROVIDER = os.getenv('AI_PROVIDER', 'groq')

3. These values stored in Django settings module and accessed via:
   - getattr(settings, 'GROQ_API_KEY', None)
   - getattr(settings, 'GROQ_MODEL', None)
   - getattr(settings, 'AI_PROVIDER', 'groq')

CURRENT CONFIGURATION:
- .env file EXISTS with: GROQ_MODEL=openai/gpt-oss-120b
- .env.example shows original: GROQ_MODEL=llama-3.3-70b-versatile


================================================================================
C. PROVIDER FLOW (DETAILED)
================================================================================

PROVIDER INSTANTIATION (ProviderFactory):

    papers/provider_factory.py::ProviderFactory.create_provider()
    {
        provider_name = getattr(settings, 'AI_PROVIDER', 'groq').strip().lower()
        
        if provider_name == 'groq':
            return GroqProvider()  [CURRENT]
        elif provider_name == 'mock':
            return MockProvider()
        else:
            raise ValueError(...)
    }


GROQ PROVIDER INITIALIZATION (papers/ai_providers.py::GroqProvider):

    def __init__(self):
        # Step 1: Reload settings to ensure fresh configuration
        from ResearchMate import settings as project_settings
        project_settings.load_env_file()
        
        # Step 2: Get API key from settings
        api_key = getattr(settings, 'GROQ_API_KEY', None)
        if not api_key:
            raise ImproperlyConfigured('GROQ_API_KEY is not configured.')
        
        # Step 3: Import Groq SDK
        import groq
        from groq import Groq
        
        # Step 4: Create Groq client (FIRST CLIENT INSTANTIATION)
        self.client = Groq(api_key=api_key)
        
        # Step 5: Get model name from settings or use hard-coded fallback
        self.model_name = getattr(settings, 'GROQ_MODEL', None) or 'llama-3.3-70b-versatile'
                                                                   [HARD-CODED FALLBACK]


GROQ PROVIDER GENERATE METHOD:

    def generate(self, prompt):
        start_time = time.perf_counter()
        response = self.client.chat.completions.create(
            model=self.model_name,        [USES self.model_name ATTRIBUTE]
            messages=[{'role': 'user', 'content': prompt}],
            temperature=0.0,              [HARD-CODED TEMPERATURE]
        )
        # ... error handling and text extraction
        return extracted_text


ALTERNATIVE GROQ CONNECTIVITY (papers/groq_connectivity.py::GroqLearningService):

This is a separate, PARALLEL implementation used in views.py
    
    def __init__(self):
        api_key = getattr(settings, 'GROQ_API_KEY', None) or os.environ.get('GROQ_API_KEY')
        self.model_name = getattr(settings, 'GROQ_MODEL', None) or os.environ.get('GROQ_MODEL', 'llama-3.3-70b-versatile')
                                                                                                     [HARD-CODED FALLBACK]
        
        from groq import Groq
        self.client = Groq(api_key=api_key)  [SECOND CLIENT INSTANTIATION]

    def generate_analysis(self, prompt):
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=[{'role': 'user', 'content': prompt}],
            temperature=0.0,
        )
        # ... extraction
        return text


GROQ CLIENT INSTANTIATION LOCATIONS:
1. papers/ai_providers.py line 87: GroqProvider.__init__
2. papers/groq_connectivity.py line 40: GroqLearningService.__init__


MODEL NAME PASSED TO GROQ:
- Both locations use: self.client.chat.completions.create(model=self.model_name, ...)
- Both read model_name from: getattr(settings, 'GROQ_MODEL', None) or 'llama-3.3-70b-versatile'


================================================================================
D. AI SERVICE FLOW
================================================================================

MAIN ORCHESTRATION (papers/ai_service.py::AIService):

    class AIService:
        def __init__(self, provider=None):
            self.provider = provider or ProviderFactory.create_provider()
        
        def build_prompt(self, feature_name, extracted_text, ...):
            # Maps feature_name to prompt builder function
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
            }
            return prompt_builder(feature_name)(extracted_text)
        
        def generate_feature(self, feature_name, extracted_text, ...):
            prompt = self.build_prompt(feature_name, extracted_text, ...)
            return self.provider.generate(prompt)


RESPONSE HANDLING:
- prompt_manager.py: Maps feature names to prompt builders
- prompts/*.py: Generate formatted prompts
- response_validator.py: Validates JSON responses
  * Handles markdown code fences
  * Cleans control characters
  * Extracts JSON from surrounding text
  * Returns (valid: bool, payload: dict, error: str)


================================================================================
E. FEATURE-BY-FEATURE FLOW
================================================================================

All features follow identical pattern:

    Feature Service
    ├─ Check PaperContent exists
    ├─ Create/reuse AIService with provider
    ├─ Call generate_feature('feature_name', extracted_text)
    │  └─ AIService.generate_feature()
    │     ├─ Build prompt using prompt builder
    │     └─ Call provider.generate(prompt)
    │        └─ GroqProvider.generate()
    │           └─ self.client.chat.completions.create(model=self.model_name, ...)
    │
    ├─ Parse/validate response
    └─ Save to database model


FEATURE 1: BEGINNER EXPLANATION
- Service: papers/services.py::process_mock_ai() [main integration]
- Prompt: papers/prompts/beginner.py::build_beginner_prompt
- Response format: JSON with keys like 'beginner_explanation', 'key_contributions', etc.
- Parser: papers/parser.py::GroqPayloadParser
- Validator: response_validator.validate_json_response()
- Database: AIAnalysis.beginner_explanation (TextField)
- Fallback: None (fails if AI returns invalid JSON)


FEATURE 2: TECHNICAL EXPLANATION
- Service: papers/technical_service.py::generate_technical_explanation()
- Prompt: papers/prompts/technical.py::build_technical_prompt
- Response format: JSON with 'technical_explanation' key
- Parser: response_validator.validate_json_response()
- Validator: Checks word count (500-800 words)
- Database: AIAnalysis.technical_explanation (TextField)
- Fallback: _build_fallback_technical_explanation() if word count invalid


FEATURE 3: GLOSSARY
- Service: papers/glossary_service.py::generate_glossary()
- Prompt: papers/prompts/glossary.py::build_glossary_prompt
- Response format: Markdown with ## Term Name structure (NOT JSON)
- Parser: _extract_glossary_sections() (regex-based)
- Database: Glossary model (term, explanation, paper_role, etc.)
- Fallback: Raises GlossaryGenerationError if parsing fails


FEATURE 4: FLASHCARDS
- Service: papers/flashcard_service.py::generate_flashcards()
- Prompt: papers/prompts/flashcards.py::build_flashcards_prompt
- Response format: JSON array in 'flashcards' key
- Parser: response_validator.validate_json_response()
- Database: Flashcard model (question, answer, difficulty, category, etc.)
- Fallback: Raises FlashcardGenerationError if validation fails


FEATURE 5: QUIZ
- Service: papers/quiz_service.py::generate_quiz()
- Prompt: papers/prompts/quiz.py::build_quiz_prompt
- Response format: JSON array in 'quiz_questions' key (10+ questions)
- Parser: response_validator.validate_json_response()
- Database: QuizQuestion model (question, options A-D, correct_answer, etc.)
- Fallback: Raises QuizGenerationError if < 10 questions parsed


FEATURE 6: VIVA
- Service: papers/viva_service.py::generate_viva_questions()
- Prompt: papers/prompts/viva.py::build_viva_prompt
- Response format: JSON array in 'viva_questions' key (8+ questions)
- Parser: response_validator.validate_json_response()
- Database: VivaQuestion model (question, suggested_answer, difficulty, etc.)
- Fallback: Raises VivaGenerationError if < 8 questions parsed


FEATURE 7: SECTION LEARNING
- Service: papers/section_learning_service.py::detect_sections(), explain_sections()
- Prompt: Two-step:
  * Step 1 (section detection): papers/prompts/section_learning.py::get_section_detection_prompt()
  * Step 2 (section explanation): papers/prompts/section_learning.py::get_single_section_explanation_prompt()
- Response format: JSON with 'sections' key (array of {title, summary, key_points, etc.})
- Parser: _clean_detection_payload() (JSON extraction)
- Database: PaperSection model (paper, title, summary, key_points, etc.)
- Fallback: Raises SectionLearningError if parsing fails


FEATURE 8: REVISION NOTES
- Service: papers/revision_notes_service.py::generate_revision_notes()
- Prompt: papers/prompts/revision_notes.py::build_revision_notes_prompt
- Response format: Markdown (plain text or code fence)
- Parser: _clean_revision_notes() (removes code fences if present)
- Database: AIAnalysis.revision_notes (TextField)
- Fallback: Raises RevisionNotesGenerationError if empty


================================================================================
F. EVERY HARD-CODED REFERENCE TO OLD MODEL
================================================================================

OLD MODEL: "llama-3.3-70b-versatile"

REFERENCE 1: papers/ai_providers.py line 86
- Type: Hard-coded fallback in GroqProvider.__init__
- Code: self.model_name = getattr(settings, 'GROQ_MODEL', None) or 'llama-3.3-70b-versatile'
- Context: Primary provider instantiation
- Runtime: ACTIVE (used if GROQ_MODEL not in settings)
- Migration impact: CRITICAL


REFERENCE 2: papers/groq_connectivity.py line 32
- Type: Hard-coded fallback in GroqLearningService.__init__
- Code: self.model_name = getattr(settings, 'GROQ_MODEL', None) or os.environ.get('GROQ_MODEL', 'llama-3.3-70b-versatile')
- Context: Alternative Groq service (used in views for connectivity testing)
- Runtime: ACTIVE (used if GROQ_MODEL not in settings or environment)
- Migration impact: CRITICAL


REFERENCE 3: ResearchMate/settings.py line 24
- Type: Hard-coded fallback in refresh_settings_from_env()
- Code: GROQ_MODEL = os.environ.get('GROQ_MODEL', 'llama-3.3-70b-versatile')
- Context: Settings initialization
- Runtime: ACTIVE (used if GROQ_MODEL not in environment)
- Migration impact: CRITICAL


REFERENCE 4: .env.example line 2
- Type: Documentation/example
- Code: GROQ_MODEL=llama-3.3-70b-versatile
- Context: Example environment file
- Runtime: NOT ACTIVE (only used for documentation)
- Migration impact: LOW (documentation only, not runtime)


REFERENCE 5: papers/tests.py line 29
- Type: Test configuration
- Code: @override_settings(DEBUG=True, GROQ_API_KEY='test-key', GROQ_MODEL='llama-3.3-70b-versatile')
- Context: Test setup
- Runtime: NOT ACTIVE (only in tests)
- Migration impact: LOW (tests only)


REFERENCE 6: papers/tests.py lines 482, 812, 848, 936
- Type: Test mock/patch text
- Code: Various test overrides with GROQ_MODEL='llama-3.3-70b-versatile'
- Context: Test configuration
- Runtime: NOT ACTIVE (only in tests)
- Migration impact: LOW (tests only)


REFERENCE 7: papers/tests.py line 31
- Type: Test assertion data
- Code: 'model': 'llama-3.3-70b-versatile' (in mock response dict)
- Context: Test expected value
- Runtime: NOT ACTIVE (only in tests)
- Migration impact: LOW (tests only)


CLASSIFICATION SUMMARY:
- Hard-coded fallbacks in RUNTIME code: 3 (papers/ai_providers.py, papers/groq_connectivity.py, ResearchMate/settings.py)
- Test-only references: 4
- Documentation-only: 1


================================================================================
G. RESPONSE PARSING & VALIDATION ARCHITECTURE
================================================================================

RESPONSE FLOW:

    Raw provider response
        ↓
    response_validator.validate_json_response()
    ├─ Removes code fences (```json ... ```)
    ├─ Cleans control characters
    ├─ Extracts JSON object if surrounded by text
    ├─ Attempts json.loads()
    └─ Returns (valid: bool, parsed: dict, error: str)
        ↓
    Feature-specific parser:
    ├─ Glossary: _extract_glossary_sections() [regex-based markdown parsing]
    ├─ Flashcards: _clean_flashcards_entries() [JSON key extraction]
    ├─ Quiz: _clean_quiz_entries() [JSON key extraction]
    ├─ Viva: _clean_viva_entries() [JSON key extraction]
    └─ Sections: _clean_detection_payload() [JSON key extraction]
        ↓
    Database models


JSON PARSING ASSUMPTIONS:
- Some features expect specific JSON keys:
  * 'flashcards' (Flashcard service)
  * 'quiz_questions' (Quiz service)
  * 'viva_questions' (Viva service)
  * 'sections' or 'section_titles' (Section learning)
- Parser is flexible: can extract "sections" from alternative keys
- Markdown glossary parsed via regex (doesn't require JSON)


TEMPERATURE SETTING:
- ALL Groq requests use temperature=0.0
- Hard-coded in:
  * papers/ai_providers.py line 167
  * papers/groq_connectivity.py lines 54, 82


================================================================================
H. IDENTIFIED ARCHITECTURAL RISKS FOR MIGRATION
================================================================================

RISK 1: THREE HARD-CODED FALLBACKS
Severity: CRITICAL
Location: 
  - papers/ai_providers.py line 86
  - papers/groq_connectivity.py line 32
  - ResearchMate/settings.py line 24
Issue: If .env file doesn't have GROQ_MODEL, system falls back to 'llama-3.3-70b-versatile'
Impact: Without changing code, model migration won't take effect
Action: MUST update all three fallback strings to new model name


RISK 2: DUPLICATE GROQ CLIENT INSTANTIATION
Severity: MEDIUM
Location:
  - papers/ai_providers.py (GroqProvider)
  - papers/groq_connectivity.py (GroqLearningService)
Issue: Two separate classes create Groq clients independently
Impact: Both must be updated with same API key and model handling
        Different code paths could behave differently
Action: Verify GroqLearningService is actually used (appears to be alternative path)


RISK 3: MULTIPLE CONFIGURATION SOURCES
Severity: MEDIUM
Sources:
  - .env file (primary)
  - Django settings (secondary)
  - os.environ (fallback in GroqLearningService)
  - Hard-coded defaults (tertiary)
Issue: Precedence order unclear, potential for inconsistency
Impact: Different code paths might use different model names
Action: Verify configuration refresh in ProviderFactory matches settings.py


RISK 4: FEATURE-SPECIFIC RESPONSE FORMAT EXPECTATIONS
Severity: LOW
Issue: Each feature has specific JSON key expectations
  - 'flashcards', 'quiz_questions', 'viva_questions', etc.
Impact: Model must return responses matching expected keys
        Prompts already specify exact JSON schema for each feature
Action: Verify new model follows same prompt instructions


RISK 5: TEMPERATURE HARD-CODED TO 0.0
Severity: LOW
Impact: Model will use temperature=0.0 regardless of .env
Action: If new model requires different temperature, code changes needed


RISK 6: RETRY BEHAVIOR
Severity: LOW
Issue: No automatic retry on model error
Impact: Users see retry button in UI
        Retry uses same model/provider
Action: Existing retry mechanism will work with new model


RISK 7: NO MODEL-SPECIFIC SPECIAL HANDLING
Severity: POSITIVE (LOW RISK)
Impact: No model-name-dependent code paths
        No feature-specific model checks
Action: Migration should work seamlessly if response format is compatible


================================================================================
I. EXACT FILES REQUIRING MODIFICATION FOR MODEL-ONLY MIGRATION
================================================================================

MUST MODIFY (3 files with 3 locations):

1. ResearchMate/settings.py
   Line 24: 
   OLD: GROQ_MODEL = os.environ.get('GROQ_MODEL', 'llama-3.3-70b-versatile')
   NEW: GROQ_MODEL = os.environ.get('GROQ_MODEL', 'openai/gpt-oss-120b')
   
   Change: Fallback string from 'llama-3.3-70b-versatile' to 'openai/gpt-oss-120b'


2. papers/ai_providers.py
   Line 86:
   OLD: self.model_name = getattr(settings, 'GROQ_MODEL', None) or 'llama-3.3-70b-versatile'
   NEW: self.model_name = getattr(settings, 'GROQ_MODEL', None) or 'openai/gpt-oss-120b'
   
   Change: Fallback string from 'llama-3.3-70b-versatile' to 'openai/gpt-oss-120b'


3. papers/groq_connectivity.py
   Line 32:
   OLD: self.model_name = getattr(settings, 'GROQ_MODEL', None) or os.environ.get('GROQ_MODEL', 'llama-3.3-70b-versatile')
   NEW: self.model_name = getattr(settings, 'GROQ_MODEL', None) or os.environ.get('GROQ_MODEL', 'openai/gpt-oss-120b')
   
   Change: Fallback string from 'llama-3.3-70b-versatile' to 'openai/gpt-oss-120b'


SHOULD UPDATE (1 file, documentation):

4. .env.example (OPTIONAL — documentation only, not runtime)
   Line 2:
   OLD: GROQ_MODEL=llama-3.3-70b-versatile
   NEW: GROQ_MODEL=openai/gpt-oss-120b
   
   Change: Example value for documentation


TEST FILES (1 file, may need updates):

5. papers/tests.py
   - Multiple @override_settings with GROQ_MODEL='llama-3.3-70b-versatile'
   - Can optionally update to new model for consistency
   - Not required for migration (tests use mocks)
   - Update recommended for maintainability


FILES THAT MUST NOT BE MODIFIED (read-only for migration):

- All feature service files (.glossary_service, flashcard_service, etc.)
- All prompt files (prompts/*.py)
- response_validator.py
- parser.py
- models.py
- views.py
- admin.py
- urls.py
- forms.py
- All template files
- Database files
- UI/UX files


================================================================================
J. FILES THAT MUST NOT BE MODIFIED
================================================================================

Architecture: NO CHANGES NEEDED

Provider Factory
- papers/provider_factory.py
  → Already abstracts provider selection
  → Works with any model name

AIService
- papers/ai_service.py
  → Already generic for all features
  → Passes model name from provider
  → No model-specific logic

Feature Services
- papers/glossary_service.py
- papers/flashcard_service.py
- papers/quiz_service.py
- papers/viva_service.py
- papers/section_learning_service.py
- papers/revision_notes_service.py
- papers/technical_service.py

Prompt Files
- papers/prompts/*.py
  → Prompts already specify exact JSON schema
  → New model inherits same prompt expectations
  → Response parsing is generic

Response Validation
- papers/response_validator.py
- papers/parser.py
  → Generic JSON parsing
  → No model-specific handling

Database
- papers/models.py
  → Already stores model name in ai_model field
  → No schema changes needed

Views & Templates
- papers/views.py
- templates/papers/**/*.html
  → Generic error handling
  → Already supports any model name
  → Displays model name from ai_model field

Admin
- papers/admin.py
  → Already displays ai_model field
  → No changes needed

Tests
- papers/tests.py
  → Test mocks are model-agnostic
  → Can optionally update test overrides for consistency


================================================================================
K. FINAL RISK ASSESSMENT
================================================================================

CRITICALITY: LOW (Minimal code changes required)

Required changes: 3 locations in 3 files (only fallback strings)
Estimated lines to change: 3 lines total
Test coverage: Good (existing tests use mocks)
Database impact: None (ai_model field already stores model name)
UI impact: None (model name already displayed)
Retry behavior: Works with any model
Error handling: Generic error messages


MIGRATION PATHWAY:

Option A (Minimal — .env only):
- Do nothing in code
- .env already has openai/gpt-oss-120b configured
- Risk: If .env missing/reset, falls back to old model

Option B (Safe — code + .env):
- Update 3 fallback strings to new model name
- Keeps .env as-is
- Guarantees correct model even if .env missing
- Recommended approach


================================================================================
L. RESPONSE FORMAT COMPATIBILITY CHECK
================================================================================

CURRENT PROMPT SCHEMA (each feature specifies exact JSON format):

Template from base.py:
{
  "beginner_explanation": "string",
  "technical_explanation": "string",
  "key_contributions": ["string"],
  "key_concepts": ["string"],
  "reading_difficulty": {"level": "string", "reason": "string"},
  "glossary": [{"term": "string", "simple_explanation": "string", "technical_explanation": "string", "example": "string"}],
  "flashcards": [{"question": "string", "answer": "string"}],
  "quiz_questions": [{"question": "string", "option_a": "string", "option_b": "string", "option_c": "string", "option_d": "string", "correct_answer": "string", "explanation": "string"}],
  "viva_questions": [{"question": "string", "suggested_answer": "string", "follow_up_question": "string"}]
}

This schema is EMBEDDED in every prompt.

NEW MODEL (openai/gpt-oss-120b) MUST:
✓ Accept same temperature=0.0 setting
✓ Return valid JSON for structured features
✓ Handle 500-12000 character prompts
✓ Follow prompt instructions
✓ Return JSON within reasonable token limits

RISK: If new model returns different JSON structure, response parsing will fail
MITIGATION: Verify new model follows system prompt structure in production tests


================================================================================
M. CONCLUSION & READINESS ASSESSMENT
================================================================================

PROJECT STATUS FOR MINIMAL MODEL-ONLY MIGRATION: ✓ READY

SUMMARY:
- Architecture is model-agnostic (no hard-coded model logic)
- Configuration system is flexible (reads from .env with code fallbacks)
- Response parsing is generic (works with any model)
- 3 trivial code changes needed to update fallback strings
- 0 database changes needed
- 0 UI changes needed
- Existing test suite provides good coverage

RECOMMENDATION: Proceed with Migration Task 3

MIGRATION SAFETY LEVEL: HIGH
- Code changes are minimal and low-risk
- No breaking changes to architecture
- Existing retry/error handling works
- ai_model field will track which model generated each response


EXACT FILES & LINES TO CHANGE:

FILE 1: ResearchMate/settings.py
  Line 24: Change fallback from 'llama-3.3-70b-versatile' to 'openai/gpt-oss-120b'

FILE 2: papers/ai_providers.py
  Line 86: Change fallback from 'llama-3.3-70b-versatile' to 'openai/gpt-oss-120b'

FILE 3: papers/groq_connectivity.py
  Line 32: Change fallback from 'llama-3.3-70b-versatile' to 'openai/gpt-oss-120b'

(OPTIONAL) FILE 4: .env.example
  Line 2: Update documentation from 'llama-3.3-70b-versatile' to 'openai/gpt-oss-120b'

================================================================================
END OF AUDIT REPORT
================================================================================
