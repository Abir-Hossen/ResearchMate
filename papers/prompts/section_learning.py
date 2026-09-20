import re


def _compact_section_text(section_text, max_chars=7000):
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
    """Build a compact prompt for headings already detected in the paper."""
    if not extracted_text:
        return ''

    compact_text = _compact_section_text(extracted_text)
    headings = re.findall(r'^##\s+(.+)$', compact_text, flags=re.MULTILINE)
    if not headings:
        headings = ['Main Content']
    heading_json = ',\n'.join(
        f'    {{"title": "{heading}", "explanation": "45-60 word paper-specific overview."}}'
        for heading in headings
    )
    heading_list = ', '.join(headings)
    return f"""You are an expert academic reading tutor. The paper headings below were detected from the extracted paper text before this request. For EACH detected heading, write exactly ONE short overview of 45-60 words grounded ONLY in that heading's text. Never exceed 70 words for any section.
Do NOT use information from another section. Do NOT invent facts, methods, datasets, or findings not present in the supplied text.
Never invent a section that is not supported by the text. Never use a sentence, a sentence fragment, a subsection heading, or a line of body text as a title.

OUTPUT FORMAT - Return ONLY valid JSON:
{{
  "sections": [
{heading_json}
  ]
}}

RULES:
- Return exactly {len(headings)} sections. The section titles must be exactly: {heading_list}.
- Do NOT include markdown, code fences, or any text outside the JSON.
- Do NOT invent facts not supported by the section text.
- Keep each explanation short, preferably 45-60 words and never over 70 words, to avoid truncation.

Detected paper sections:
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
