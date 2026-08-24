import re


def _compact_section_text(section_text, max_chars=4000):
    """Compact paper text to stay within token limits while preserving content."""
    if not section_text:
        return ''

    cleaned = re.sub(r'\n{3,}', '\n\n', section_text)
    if len(cleaned) <= max_chars:
        return cleaned.strip()

    truncated = cleaned[:max_chars]
    if ' ' in truncated:
        truncated = truncated.rsplit(' ', 1)[0]
    return truncated + ' [truncated]'


def build_section_learning_prompt(extracted_text, paper_context=None):
    """Build a prompt for fixed-section paper explanation generation."""
    if not extracted_text:
        return ''

    compact_text = _compact_section_text(extracted_text)
    return f"""You are an expert academic reading tutor. Below is a paper with labeled sections. For EACH labeled section below, write exactly ONE concise explanation of 60-90 words grounded ONLY in that section's text.
Do NOT use information from another section. Do NOT invent facts, methods, datasets, or findings not present in the supplied text.

If a section shows "[No text available for this section]", write "This section is not present in the paper." for that section only.

OUTPUT FORMAT - Return ONLY valid JSON:
{{
  "sections": [
    {{
      "title": "Abstract",
      "explanation": "60-90 word paper-specific explanation."
    }},
    {{
      "title": "Introduction",
      "explanation": "60-90 word paper-specific explanation."
    }},
    {{
      "title": "Related Work",
      "explanation": "60-90 word paper-specific explanation."
    }},
    {{
      "title": "Methodology",
      "explanation": "60-90 word paper-specific explanation."
    }},
    {{
      "title": "Results and Discussion",
      "explanation": "60-90 word paper-specific explanation."
    }},
    {{
      "title": "Conclusion",
      "explanation": "60-90 word paper-specific explanation."
    }}
  ]
}}

RULES:
- Return exactly 6 sections. The section titles must be exactly: Abstract, Introduction, Related Work, Methodology, Results and Discussion, Conclusion.
- Do NOT include markdown, code fences, or any text outside the JSON.
- Do NOT invent facts not supported by the section text.
- Keep each explanation under 90 words to avoid truncation.

Labeled paper sections:
{compact_text}"""


def get_section_detection_prompt(extracted_text):
    """Build section detection prompt (legacy support for compatibility)."""
    return build_section_learning_prompt(extracted_text)


def get_single_section_explanation_prompt(section_title, section_text, paper_context=None):
    """Build single-section explanation prompt."""
    if not section_text:
        return ''

    compact_text = _compact_section_text(section_text)
    return f"""You are an expert academic reading tutor. Explain the "{section_title}" section below in exactly 80-120 words, grounded ONLY in the supplied text.
Do NOT use information from another section. Do NOT invent facts, methods, datasets, or findings not present in the supplied text.

OUTPUT FORMAT - Return ONLY valid JSON:
{{
  "sections": [
    {{
      "title": "{section_title}",
      "explanation": "80-120 word paper-specific explanation."
    }}
  ]
}}

RULES:
- Return exactly 1 section.
- Do NOT include markdown, code fences, or any text outside the JSON.
- Do NOT invent facts not supported by the section text.

Paper text:
{compact_text}
"""
