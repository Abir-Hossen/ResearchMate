def _compact_section_text(section_text, max_chars=6000):
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
    return f"""You are an expert academic reading tutor. Analyze the research paper text below and identify its actual sections.

STEP 1 - IDENTIFY SECTIONS:
- Read through the paper text carefully.
- Identify ALL major sections that genuinely exist in the paper.
- Valid section names include: Abstract, Introduction, Related Work, Literature Review, Background, Methodology, Methods, Materials and Methods, Proposed Method, System Architecture, Implementation, Dataset, Experimental Setup, Experiments, Results, Discussion, Limitations, Conclusion, Future Work.
- IGNORE these if they appear: References, Bibliography, Acknowledgements, Appendix.
- Return between 3 and 8 sections. Include every meaningful section you can find.
- Only omit a section if it genuinely does not exist in the paper.

STEP 2 - WRITE EXPLANATIONS:
- For each section, write exactly ONE concise explanation of 100-150 words.
- Every explanation MUST reference specific content from the paper (methods, datasets, results, claims, numbers, technical details).
- Do NOT write generic academic filler. Do NOT provide a general paper summary.
- Each explanation should help a student understand what that specific section contributes to the paper.

OUTPUT FORMAT - Return ONLY valid JSON:
{{
  "sections": [
    {{
      "title": "Exact section name from the paper",
      "explanation": "100-150 word paper-specific explanation."
    }}
  ]
}}

RULES:
- Return between 3 and 8 sections. Include ALL sections that exist.
- Do NOT include markdown, code fences, or any text outside the JSON.
- Do NOT invent facts or sections not supported by the paper text.

Paper text:
{compact_text}
"""


def get_section_detection_prompt(extracted_text):
    """Build section detection prompt (legacy support for compatibility)."""
    return build_section_learning_prompt(extracted_text)


def get_single_section_explanation_prompt(section_title, section_text, paper_context=None):
    """Build single-section explanation prompt."""
    return build_section_learning_prompt(section_text, paper_context=paper_context)
