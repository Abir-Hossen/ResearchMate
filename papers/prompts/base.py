def build_feature_prompt(extracted_text, feature_name, instruction):
    """Create a JSON-focused prompt template for a single AI feature."""
    return f"""You are generating structured data for a software application.
You are generating {feature_name} for a research paper.
Follow these instructions exactly:
{instruction}

Return ONLY valid JSON.
Do NOT include markdown, code fences, explanations, introductory text, comments, or natural-language prose.
Return ONLY one valid JSON object.

Use this schema exactly:
{{
  "beginner_explanation": "string",
  "technical_explanation": "string",
  "key_contributions": ["string"],
  "key_concepts": ["string"],
  "reading_difficulty": {{"level": "string", "reason": "string"}},
  "glossary": [{{"term": "string", "simple_explanation": "string", "technical_explanation": "string", "example": "string"}}],
  "flashcards": [{{"question": "string", "answer": "string"}}],
  "quiz_questions": [{{"question": "string", "option_a": "string", "option_b": "string", "option_c": "string", "option_d": "string", "correct_answer": "string", "explanation": "string"}}],
  "viva_questions": [{{"question": "string", "suggested_answer": "string", "follow_up_question": "string"}}]
}}

Return a concise, useful response grounded in the paper text below.

Paper text:
{extracted_text[:12000]}
"""
