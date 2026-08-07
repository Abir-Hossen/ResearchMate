def _compact_section_text(section_text, max_chars=6000):
    if not section_text:
        return ''

    cleaned = ' '.join((section_text or '').split())
    if len(cleaned) <= max_chars:
        return cleaned

    truncated = cleaned[:max_chars]
    if ' ' in truncated:
        truncated = truncated.rsplit(' ', 1)[0]
    return truncated + ' [truncated]'


def build_section_learning_prompt(section_title, section_text=None):
    if section_text is None:
        return f"""You are a reading tutor for a research paper.

Analyze the paper text below and identify every major section that should be explained to a student.

Paper text:
{section_title}

Return ONLY valid JSON with this schema:
{{
  "sections": [
    {{
      "title": "Section Name",
      "order": 1
    }}
  ]
}}

When you later explain a section, use this schema:
{{
  "summary": "A concise explanation",
  "purpose": "Why this section exists",
  "key_points": ["..."],
  "important_terms": ["..."],
  "student_note": "What the student should understand"
}}

Rules:
- Do not stop after Introduction or Related Work.
- cover the full paper
- Use short, clear section titles.
- Return valid JSON only.
"""

    compact_text = _compact_section_text(section_text)
    return f"""You are a reading tutor for a research paper.

Explain only the section below. Do not summarize the whole paper.

Section title:
{section_title}

Section text:
{compact_text}

Return ONLY valid JSON with this schema:
{{
  "summary": "A detailed but concise explanation of what the section says and why it matters",
  "purpose": "Why this section exists in the paper and what role it plays for the reader",
  "conclusion": "A short closing takeaway that reinforces the main point of the section",
  "key_points": ["A specific insight from the section", "A second specific insight from the section", "A third specific insight from the section"],
  "important_terms": ["A technical or domain-specific term from the section"],
  "student_note": "What the student should understand after reading this section"
}}

Rules:
- Do not copy text from the paper.
- Do not write generic explanations.
- Make the explanation specific to this section only.
- Include concrete details whenever the section mentions methods, architecture, datasets, experiments, metrics, findings, limitations, or conclusions.
- For methodology sections, mention the approach, components, workflow, or design choice.
- For results/discussion sections, mention observed outcomes, evidence, metrics, limitations, or comparison points if they appear in the text.
- Keep the answer concise but substantive.
- Return valid JSON only.
"""


def get_section_detection_prompt(extracted_text):
    return build_section_learning_prompt(extracted_text)


def get_single_section_explanation_prompt(section_title, section_text):
    return build_section_learning_prompt(section_title, section_text)
