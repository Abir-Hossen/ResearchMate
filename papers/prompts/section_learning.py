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
    return f"""You are an expert academic reading tutor. Analyze the research paper text below and explain the following 6 sections.

REQUIRED SECTIONS:
1. Abstract
2. Introduction
3. Related Work
4. Methodology
5. Results and Discussion
6. Conclusion

For each section, write exactly ONE concise explanation of 80-120 words.
Every explanation MUST reference specific content from the paper (methods, datasets, results, claims, numbers, technical details).
Do NOT write generic academic filler.

If a section does not exist in the paper, write "This section is not present in the paper." for that section only.

OUTPUT FORMAT - Return ONLY valid JSON:
{{
  "sections": [
    {{
      "title": "Abstract",
      "explanation": "80-120 word paper-specific explanation."
    }},
    {{
      "title": "Introduction",
      "explanation": "80-120 word paper-specific explanation."
    }},
    {{
      "title": "Related Work",
      "explanation": "80-120 word paper-specific explanation."
    }},
    {{
      "title": "Methodology",
      "explanation": "80-120 word paper-specific explanation."
    }},
    {{
      "title": "Results and Discussion",
      "explanation": "80-120 word paper-specific explanation."
    }},
    {{
      "title": "Conclusion",
      "explanation": "80-120 word paper-specific explanation."
    }}
  ]
}}

RULES:
- Return exactly 6 sections in the order shown above.
- Do NOT include markdown, code fences, or any text outside the JSON.
- Do NOT invent facts not supported by the paper text.

Paper text:
{compact_text}
"""


def get_section_detection_prompt(extracted_text):
    """Build section detection prompt (legacy support for compatibility)."""
    return build_section_learning_prompt(extracted_text)


def get_single_section_explanation_prompt(section_title, section_text, paper_context=None):
    """Build single-section explanation prompt."""
    return build_section_learning_prompt(section_text, paper_context=paper_context)
