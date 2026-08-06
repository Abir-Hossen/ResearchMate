import re
from typing import List, Dict


HEADING_KEYWORDS = (
    'abstract',
    'introduction',
    'related work',
    'background',
    'literature review',
    'methodology',
    'methods',
    'materials and methods',
    'system architecture',
    'proposed method',
    'implementation',
    'dataset',
    'experimental setup',
    'experiments',
    'results',
    'discussion',
    'limitations',
    'conclusion',
    'future work',
    'references',
    'bibliography',
    'acknowledgements',
    'appendix',
)

STOP_HEADINGS = {'references', 'bibliography', 'acknowledgements', 'appendix'}


def _normalize_text(text: str) -> str:
    return re.sub(r'\s+', ' ', (text or '').strip())


def _looks_like_heading(line: str) -> bool:
    text = re.sub(r'\s+', ' ', line or '').strip()
    if not text:
        return False

    lowered = text.lower()
    if lowered in STOP_HEADINGS:
        return True

    if any(lowered == keyword or lowered.startswith(keyword + ':') or lowered.startswith(keyword + ' ') for keyword in HEADING_KEYWORDS):
        return True

    if re.match(r'^(#{1,6}|\d+(?:\.\d+)*[\.):-]\s*)', text):
        return True

    if re.match(r'^(?:[A-Z][A-Za-z0-9/&()\-]{2,80}|[A-Z][A-Za-z0-9/&()\-]{2,80}(?:\s+[A-Z][A-Za-z0-9/&()\-]{2,80}){0,4})\s*[:.]$', text):
        return True

    if len(text.split()) <= 6 and text.endswith(':'):
        return True

    return False


def _split_heading_and_body(line: str) -> tuple[str | None, str | None]:
    text = re.sub(r'\s+', ' ', line or '').strip()
    if not text:
        return None, None

    lowered = text.lower()
    if lowered in STOP_HEADINGS:
        return lowered, None

    if any(lowered == keyword or lowered.startswith(keyword + ':') or lowered.startswith(keyword + ' ') or lowered.startswith(keyword + '.') for keyword in HEADING_KEYWORDS):
        match = re.match(r'^(#{1,6}\s*)?(?P<title>[A-Za-z][A-Za-z0-9/&()\-]{1,80})(?P<delimiter>\s*[:.-]\s*)(?P<body>.*)$', text)
        if match:
            title = match.group('title').strip().rstrip(':')
            body = match.group('body').strip()
            return title, body or None

        for keyword in HEADING_KEYWORDS:
            if lowered == keyword or lowered.startswith(keyword + ':') or lowered.startswith(keyword + ' ') or lowered.startswith(keyword + '.'):
                title = text.split('.', 1)[0].split(':', 1)[0].split(' ', 1)[0]
                if title:
                    return title, None

    return None, None


def parse_sections(extracted_text: str) -> List[Dict[str, str]]:
    """Split academic paper text into section blocks using local heuristics."""
    if not extracted_text or not extracted_text.strip():
        return []

    lines = [line.rstrip() for line in extracted_text.splitlines()]
    sections: List[Dict[str, str]] = []
    current_title = None
    current_lines: List[str] = []

    def flush_section(title: str | None, lines_list: List[str]) -> None:
        if not title:
            return
        text = '\n'.join(line.strip() for line in lines_list if line.strip())
        if not text.strip():
            return
        sections.append({'title': title, 'text': text.strip()})

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            if current_title is not None:
                current_lines.append('')
            continue

        heading_title, body = _split_heading_and_body(line)
        if heading_title is not None:
            if current_title is not None:
                flush_section(current_title, current_lines)
                current_lines = []

            cleaned_title = heading_title
            if cleaned_title.startswith('#'):
                cleaned_title = re.sub(r'^#{1,6}\s*', '', cleaned_title)
            cleaned_title = cleaned_title.strip().rstrip(':')

            if cleaned_title.lower() in STOP_HEADINGS:
                break

            current_title = cleaned_title or 'Section'
            if body:
                current_lines.append(body)
            continue

        if current_title is None:
            current_title = 'Main Content'

        current_lines.append(raw_line)

    if current_title is not None:
        flush_section(current_title, current_lines)

    if not sections:
        return [{'title': 'Main Content', 'text': _normalize_text(extracted_text)}]

    return sections
