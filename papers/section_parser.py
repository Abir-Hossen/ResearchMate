import re
from typing import List, Dict, Tuple


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
)

STOP_HEADINGS = {'references', 'bibliography', 'acknowledgements', 'appendix'}

KNOWN_HEADING_MAP = {
    'abstract': 'Abstract',
    'introduction': 'Introduction',
    'related work': 'Related Work',
    'background': 'Background',
    'literature review': 'Literature Review',
    'methodology': 'Methodology',
    'methods': 'Methods',
    'materials and methods': 'Materials and Methods',
    'system architecture': 'System Architecture',
    'proposed method': 'Proposed Method',
    'implementation': 'Implementation',
    'dataset': 'Dataset',
    'experimental setup': 'Experimental Setup',
    'experiments': 'Experiments',
    'results': 'Results',
    'discussion': 'Discussion',
    'limitations': 'Limitations',
    'conclusion': 'Conclusion',
    'future work': 'Future Work',
}


def _normalize_text(text: str) -> str:
    return re.sub(r'\s+', ' ', (text or '').strip())


def _normalize_heading_title(raw_title: str) -> str:
    title = _normalize_text(raw_title)
    title = re.sub(r'^#{1,6}\s*', '', title)
    title = re.sub(r'^(?:section\s*)?(?:[ivxlcdm]+\.|[a-z]\.)?\s*', '', title, flags=re.IGNORECASE)
    title = re.sub(r'^\d+(?:\.\d+)*[\.):-]\s*', '', title)
    title = title.strip().rstrip(':').strip()
    if not title:
        return raw_title.strip()
    lowered = title.lower()
    if lowered in KNOWN_HEADING_MAP:
        return KNOWN_HEADING_MAP[lowered]
    if lowered.startswith(tuple(k + ' ' for k in KNOWN_HEADING_MAP)):
        for key, value in KNOWN_HEADING_MAP.items():
            if lowered == key or lowered.startswith(key + ' '):
                return value
    return title if title else raw_title.strip()


def _split_heading_and_body(line: str) -> Tuple[str | None, str | None]:
    text = _normalize_text(line)
    if not text:
        return None, None

    lowered = text.lower()
    if lowered in STOP_HEADINGS:
        return lowered, None

    for keyword in HEADING_KEYWORDS:
        if lowered == keyword:
            return text, None
        pattern = re.compile(r'^' + re.escape(keyword) + r'([\s:\-–—\.]+)(.*)$', re.IGNORECASE)
        match = pattern.match(text)
        if match:
            title = keyword
            body = match.group(2).strip()
            return title, body or None

    return None, None


def parse_sections(extracted_text: str) -> List[Dict[str, str]]:
    """Split academic paper text into section blocks using strict local heuristics."""
    if not extracted_text or not extracted_text.strip():
        return []

    lines = [line.rstrip() for line in extracted_text.splitlines()]
    sections: List[Dict[str, str]] = []
    current_title = None
    current_lines: List[str] = []
    seen_titles: set = set()

    def flush_section(title: str | None, lines_list: List[str]) -> None:
        if not title:
            return
        normalized = _normalize_heading_title(title)
        if normalized.lower() in seen_titles:
            return
        seen_titles.add(normalized.lower())
        text = '\n'.join(line.strip() for line in lines_list if line.strip())
        if not text.strip():
            return
        sections.append({'title': normalized, 'text': text.strip(), 'order': len(sections) + 1})

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            if current_title is not None:
                current_lines.append('')
            continue

        heading_title, body = _split_heading_and_body(line)
        if heading_title is not None:
            normalized_heading = _normalize_heading_title(heading_title)
            if normalized_heading.lower() in STOP_HEADINGS:
                if current_title is not None:
                    flush_section(current_title, current_lines)
                    current_title = None
                    current_lines = []
                break

            if current_title is not None:
                flush_section(current_title, current_lines)
                current_lines = []

            current_title = normalized_heading
            if body:
                current_lines.append(body)
            continue

        if current_title is None:
            current_title = 'Main Content'

        current_lines.append(raw_line)

    if current_title is not None:
        flush_section(current_title, current_lines)

    if not sections:
        return [{'title': 'Main Content', 'text': _normalize_text(extracted_text), 'order': 1}]

    for index, section in enumerate(sections, start=1):
        section['order'] = index

    return sections
