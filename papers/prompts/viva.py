def build_viva_prompt(extracted_text):
    """Build a focused prompt for viva preparation question generation."""
    instruction = (
        "Create 12-15 paper-specific viva preparation questions for a university thesis defense. "
        "Generate questions only from the uploaded paper and never invent methods, datasets, or models that are not present in the paper. "
        "Do not generate multiple-choice questions or glossary-style definitions. "
        "Group them into three categories: Basic Understanding, Technical Understanding, and Critical Thinking. "
        "For each question include a concise answer (100-180 words), a difficulty level (Easy, Medium, or Hard), a category, and an examiner tip."
    )
    return f"""You are generating structured data for a software application.
You are generating viva preparation questions for a research paper.
Follow these instructions exactly:
{instruction}

Return ONLY valid JSON.
Do NOT include markdown, code fences, explanations, introductory text, comments, or natural-language prose.
Return ONLY one valid JSON object.

Use this schema exactly:
{{
  "viva_questions": [
    {{
      "question": "string",
      "suggested_answer": "string",
      "follow_up_question": "string",
      "difficulty": "Easy|Medium|Hard",
      "category": "Basic Understanding|Technical Understanding|Critical Thinking",
      "examiner_tip": "string"
    }}
  ]
}}

Return a concise, useful response grounded in the paper text below.
Aim for 12-15 questions total, with a mix of the three categories.

Paper text:
{extracted_text[:12000]}
"""
