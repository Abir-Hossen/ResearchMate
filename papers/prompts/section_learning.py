def _compact_section_text(section_text, max_chars=8000):
    """Compact paper text to stay within token limits while preserving content."""
    if not section_text:
        return ''

    cleaned = ' '.join((section_text or '').split())
    if len(cleaned) <= max_chars:
        return cleaned

    truncated = cleaned[:max_chars]
    if ' ' in truncated:
        truncated = truncated.rsplit(' ', 1)[0]
    return truncated + ' [truncated]'


def build_section_learning_prompt(extracted_text, paper_context=None):
    """Build a prompt for whole-paper section detection and explanation generation."""
    if not extracted_text:
        return ''

    compact_text = _compact_section_text(extracted_text)
    return f"""You are an expert academic reading tutor. Analyze the following research paper text. Identify every major section that exists in the paper, then write a professional, paper-specific explanation for each section.

Paper text:
{compact_text}

Return ONLY valid JSON with this exact schema:
{{
  "sections": [
    {{
      "title": "Section Name",
      "explanation": "100-150 word professional explanation grounded in the paper text."
    }}
  ]
}}

Rules:
- Identify ONLY sections that genuinely exist in the paper. Do not invent sections.
- Use clear, short section titles (e.g., Abstract, Introduction, Related Work, Methodology, Results, Conclusion).
- If the paper has no clear section headings, return a single section titled "Main Content".
- Each explanation must be 100-150 words.
- Each explanation must reference specific content from the paper (methods, datasets, results, claims, etc.).
- Write in a professional academic tone suitable for a university student.
- Do NOT include markdown, code fences, or any text outside the JSON object.
- Return ONLY the JSON object, nothing else.
"""


def get_section_detection_prompt(extracted_text):
    """Build section detection prompt (legacy support for compatibility)."""
    return build_section_learning_prompt(extracted_text)


def get_single_section_explanation_prompt(section_title, section_text, paper_context=None):
    """Build single-section explanation prompt."""
    return build_section_learning_prompt(section_text, paper_context=paper_context)
