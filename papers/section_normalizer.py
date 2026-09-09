"""Section Learning heading detection, concept normalization, and paper digest.

This module is used ONLY by the Section Learning feature
(``papers.section_learning_service`` and ``papers.prompts.section_learning``).

It solves two Section-Learning-specific problems:

1. **Concept normalization** — the same conceptual section appears under many
   headings ("Literature Review" / "Background" → Related Work,
   "Materials and Methods" / "Proposed Approach" → Methodology,
   "Experimental Results" / "Evaluation" → Results, "Conclusions and Future
   Work" → Conclusion). Classification runs on *heading lines only*, never on
   arbitrary body text, so unrelated prose is never misclassified.

2. **Whole-paper coverage** — instead of sending only the first N characters of
   the paper to the AI (which meant later sections such as Results and
   Conclusion were never visible), :func:`build_structure_digest` samples an
   excerpt from every detected section across the whole document within the same
   character budget.

Nothing here is imported by any other AI feature.
"""

import re

# Ordered major research concepts that Section Learning must try to cover.
CONCEPT_ABSTRACT = 'abstract'
CONCEPT_INTRODUCTION = 'introduction'
CONCEPT_RELATED_WORK = 'related_work'
CONCEPT_METHODOLOGY = 'methodology'
CONCEPT_RESULTS = 'results'
CONCEPT_CONCLUSION = 'conclusion'

MAJOR_CONCEPT_ORDER = (
    CONCEPT_ABSTRACT,
    CONCEPT_INTRODUCTION,
    CONCEPT_RELATED_WORK,
    CONCEPT_METHODOLOGY,
    CONCEPT_RESULTS,
    CONCEPT_CONCLUSION,
)

MAJOR_CONCEPT_LABELS = {
    CONCEPT_ABSTRACT: 'Abstract',
    CONCEPT_INTRODUCTION: 'Introduction',
    CONCEPT_RELATED_WORK: 'Related Work / Literature Review',
    CONCEPT_METHODOLOGY: 'Methodology / Proposed Method',
    CONCEPT_RESULTS: 'Results / Evaluation / Discussion',
    CONCEPT_CONCLUSION: 'Conclusion',
}

# Digest budget. Kept in one place so the prompt stays inside its size budget.
SECTION_DIGEST_MAX_CHARS = 8000
SECTION_DIGEST_MIN_EXCERPT = 320
SECTION_DIGEST_MAX_EXCERPT = 1800
TRUNCATION_MARKER = ' [truncated]'

# Headings that must never become learning sections.
_EXCLUDED_PATTERNS = (
    r'^references?$',
    r'^reference\s+list$',
    r'^bibliograph(?:y|ies)$',
    r'^acknowledge?ments?$',
    r'^acknowledgment\s+of\s+funding$',
    r'^appendi(?:x|ces)\b',
    r'^supplement(?:ary|al)\b',
    r'^author\s+contributions?$',
    r'^conflicts?\s+of\s+interest$',
    r'^funding$',
    r'^data\s+availability\b',
    r'^ethics?\s+statement$',
)

# Concept patterns, ordered from most specific to most general. Each pattern is
# matched against a cleaned heading (numbering and punctuation removed).
_CONCEPT_PATTERNS = (
    (CONCEPT_ABSTRACT, (
        r'^(?:the\s+)?abstract\b',
        r'^executive\s+summary\b',
    )),
    (CONCEPT_CONCLUSION, (
        r'^(?:the\s+)?conclusions?\b',
        r'^(?:the\s+)?concluding\s+remarks\b',
        r'^(?:the\s+)?summary\s+and\s+conclusions?\b',
        r'^(?:the\s+)?conclusions?\s+and\s+(?:future|further)\b',
        r'^(?:the\s+)?final\s+remarks\b',
        r'^(?:the\s+)?closing\s+remarks\b',
    )),
    (CONCEPT_RELATED_WORK, (
        r'^(?:the\s+)?related\s+works?\b',
        r'^(?:the\s+)?related\s+(?:studies|research|literature)\b',
        r'^(?:the\s+)?literature\s+(?:review|survey|study)\b',
        r'^(?:the\s+)?review\s+of\s+(?:the\s+)?literature\b',
        r'^(?:the\s+)?background\b',
        r'^(?:the\s+)?previous\s+works?\b',
        r'^(?:the\s+)?prior\s+(?:works?|art|studies)\b',
        r'^(?:the\s+)?existing\s+(?:works?|systems?|approaches)\b',
        r'^(?:the\s+)?state\s+of\s+the\s+art\b',
        r'^(?:the\s+)?theoretical\s+(?:background|framework)\b',
    )),
    (CONCEPT_INTRODUCTION, (
        r'^(?:the\s+)?introductions?\b',
        r'^(?:the\s+)?motivation\b',
        r'^(?:the\s+)?problem\s+statement\b',
    )),
    (CONCEPT_RESULTS, (
        r'^(?:the\s+)?results?\b',
        r'^(?:the\s+)?experimental\s+results?\b',
        r'^(?:the\s+)?experiments?\b',
        r'^(?:the\s+)?experiments?\s+and\s+(?:results?|analysis|discussions?)\b',
        r'^(?:the\s+)?(?:performance\s+|empirical\s+|quantitative\s+|comparative\s+)?evaluations?\b',
        r'^(?:the\s+)?discussions?\b',
        r'^(?:the\s+)?findings\b',
        r'^(?:the\s+)?observations\b',
        r'^(?:the\s+)?ablation\b',
        r'^(?:the\s+)?comparative\s+(?:analysis|study)\b',
        r'^(?:the\s+)?performance\s+analysis\b',
        r'^(?:the\s+)?analysis\s+of\s+results?\b',
    )),
    (CONCEPT_METHODOLOGY, (
        r'^(?:the\s+)?methodolog(?:y|ies)\b',
        r'^(?:the\s+)?methods?\b',
        r'^(?:the\s+)?materials?\s+and\s+methods?\b',
        r'^(?:the\s+)?research\s+(?:method|methodology|design|approach)\b',
        r'^(?:the\s+)?(?:proposed|our|the\s+proposed)\s+(?:method|methodolog(?:y|ies)|approach|model|system|framework|architecture|solution|technique|algorithm|pipeline|work)s?\b',
        r'^(?:the\s+)?system\s+(?:design|architecture|model|overview|implementation)\b',
        r'^(?:the\s+)?model\s+(?:architecture|design)\b',
        r'^(?:the\s+)?implementations?\b',
        r'^(?:the\s+)?experimental\s+(?:setup|set-up|design|procedure|protocol|configuration)\b',
        r'^(?:the\s+)?design\s+and\s+implementation\b',
        r'^(?:the\s+)?data\s+collection\b',
        r'^(?:the\s+)?approach\b',
    )),
)

# Additional headings that are genuine paper sections but are not one of the six
# major concepts. They are still valid learning sections and are used as block
# boundaries when building the digest.
_OTHER_HEADING_PATTERNS = (
    r'^datasets?\b',
    r'^data\s+(?:set|sets|description|preparation|preprocessing)\b',
    r'^limitations?\b',
    r'^threats?\s+to\s+validity\b',
    r'^future\s+works?\b',
    r'^future\s+(?:directions|scope|research)\b',
    r'^feature\s+(?:extraction|engineering|selection)\b',
    r'^preliminaries\b',
    r'^notation\b',
    r'^problem\s+(?:formulation|definition)\b',
    r'^requirements?\s+analysis\b',
    r'^case\s+study\b',
    r'^user\s+study\b',
    r'^ethical\s+considerations?\b',
    r'^tools?\s+and\s+technolog(?:y|ies)\b',
    r'^training\s+(?:details|procedure|setup)\b',
    r'^evaluation\s+metrics?\b',
    r'^discussion\s+and\s+limitations?\b',
    r'^main\s+content$',
)

_MAX_HEADING_WORDS = 8
_NUMBER_PREFIX_RE = re.compile(
    r'^(?:section\s+)?(?:\d+(?:\.\d+)*|[ivxlcdm]{1,6}|[a-z])[.):\-\s]+',
    re.IGNORECASE,
)
_MARKDOWN_PREFIX_RE = re.compile(r'^[#>*\-\u2022\s]+')

# Punctuation that only occurs in running prose, never in a section heading.
# PDF extraction of two-column papers produces wrapped body lines such as
# "methods, however, were validated on relatively small private", which must
# never be mistaken for the Methodology heading.
_PROSE_PUNCTUATION_RE = re.compile(r'[,;()\[\]{}"\u201c\u201d\u2018\u2019\u2013\u2014=%<>|/\\]')
_TERMINAL_PUNCTUATION_RE = re.compile(r'[.,;!?\-\u2013\u2014]$')

# A heading does not contain a finite verb.
_VERB_WORDS = frozenset({
    'is', 'are', 'was', 'were', 'am', 'be', 'been', 'being',
    'has', 'have', 'had', 'do', 'does', 'did',
    'can', 'could', 'will', 'would', 'shall', 'should', 'may', 'might', 'must',
    'cannot', 'showed', 'shows', 'shown', 'used', 'required', 'submitted', 'validated',
    'obtained', 'presented', 'reported', 'observed', 'achieved',
})

# A heading does not end with a function word; a wrapped prose line often does.
_TRAILING_FUNCTION_WORDS = frozenset({
    'a', 'an', 'the', 'but', 'if', 'of', 'in', 'on', 'at', 'to', 'for',
    'from', 'by', 'with', 'without', 'as', 'than', 'that', 'which', 'while', 'when',
    'into', 'onto', 'over', 'under', 'between', 'among', 'per', 'via', 'their', 'its',
    'our', 'this', 'these', 'those', 'such', 'more', 'most', 'both', 'each', 'other',
})

# Exact canonical heading phrases. These are accepted even when a PDF extracted
# them in lower case, because an exact match cannot be a prose fragment.
_CANONICAL_HEADINGS = frozenset({
    'abstract', 'introduction', 'motivation', 'problem statement',
    'related work', 'related works', 'literature review', 'review of the literature',
    'background', 'background and related work', 'previous work', 'prior work',
    'state of the art', 'theoretical background',
    'methodology', 'methods', 'materials and methods', 'material and methods',
    'proposed method', 'proposed methodology', 'proposed approach', 'proposed system',
    'proposed model', 'proposed framework', 'research methodology', 'research method',
    'system architecture', 'system design', 'system overview', 'model architecture',
    'implementation', 'experimental setup', 'experimental design', 'data collection',
    'results', 'result', 'results and discussion', 'results and analysis',
    'experiments', 'experiment', 'experimental results', 'experiments and results',
    'evaluation', 'performance evaluation', 'performance analysis', 'evaluation metrics',
    'discussion', 'discussions', 'findings', 'ablation study',
    'conclusion', 'conclusions', 'conclusion and future work', 'conclusions and future work',
    'summary and conclusion', 'concluding remarks',
    'limitations', 'future work', 'future works',
    'references', 'bibliography', 'acknowledgement', 'acknowledgements',
    'acknowledgment', 'acknowledgments', 'appendix',
})


def collapse_whitespace(value):
    return re.sub(r'\s+', ' ', str(value or '')).strip()


def clean_heading_text(raw_title):
    """Strip markdown markers, numbering, and trailing punctuation from a heading."""
    title = collapse_whitespace(raw_title)
    if not title:
        return ''

    title = _MARKDOWN_PREFIX_RE.sub('', title)
    previous = None
    while previous != title:
        previous = title
        title = _NUMBER_PREFIX_RE.sub('', title).strip()

    title = title.strip().strip('*_').strip()
    title = re.sub(r'[\s:.\-–—]+$', '', title).strip()
    return title


def looks_like_heading_text(raw_line):
    """True when text is structurally a section heading rather than prose.

    This is the guard that keeps wrapped body lines produced by PDF extraction
    (for example "methods, however, were validated on relatively small private")
    out of the section list. It checks structure only, so unusual but genuine
    headings such as "System Overview and Contributions" are still accepted.
    """
    raw = collapse_whitespace(raw_line)
    if not raw:
        return False

    cleaned = clean_heading_text(raw)
    if not cleaned:
        return False

    # An exact canonical heading is always accepted, even in lower case.
    if cleaned.lower() in _CANONICAL_HEADINGS:
        return True

    if _PROSE_PUNCTUATION_RE.search(raw) or _TERMINAL_PUNCTUATION_RE.search(raw):
        return False

    words = cleaned.split()
    if not words or len(words) > _MAX_HEADING_WORDS:
        return False

    first_letter = next((char for char in cleaned if char.isalpha()), '')
    if not first_letter or not first_letter.isupper():
        return False

    lowered_words = [re.sub(r'[^a-z0-9]', '', word.lower()) for word in words]
    if any(word in _VERB_WORDS for word in lowered_words):
        return False
    if len(lowered_words) > 1 and lowered_words[-1] in _TRAILING_FUNCTION_WORDS:
        return False

    return True


def is_excluded_heading(raw_title):
    """True for back-matter headings that must never become learning sections."""
    cleaned = clean_heading_text(raw_title).lower()
    if not cleaned:
        return False
    return any(re.match(pattern, cleaned) for pattern in _EXCLUDED_PATTERNS)


def classify_heading(raw_title):
    """Map a heading to one of the six major concepts, or '' when it is not one.

    Only heading-like text is classified, so prose that happens to begin with a
    concept keyword is never treated as a section.
    """
    if not looks_like_heading_text(raw_title):
        return ''

    cleaned = clean_heading_text(raw_title).lower()
    if not cleaned or len(cleaned.split()) > _MAX_HEADING_WORDS:
        return ''
    if any(re.match(pattern, cleaned) for pattern in _EXCLUDED_PATTERNS):
        return ''

    for concept, patterns in _CONCEPT_PATTERNS:
        if any(re.match(pattern, cleaned) for pattern in patterns):
            return concept
    return ''


def _is_other_known_heading(cleaned_lower):
    return any(re.match(pattern, cleaned_lower) for pattern in _OTHER_HEADING_PATTERNS)


def looks_like_section_heading(line):
    """True when a line is a recognizable paper section heading.

    Requires both heading structure and known section vocabulary, so ordinary
    title-case lines (author names, figure captions, table labels) are ignored
    when the paper is split into blocks.
    """
    if not looks_like_heading_text(line):
        return False

    cleaned = clean_heading_text(line)
    lowered = cleaned.lower()
    if any(re.match(pattern, lowered) for pattern in _EXCLUDED_PATTERNS):
        return True
    if classify_heading(line):
        return True
    return _is_other_known_heading(lowered)


def normalize_section_title(raw_title):
    """Canonical comparison key for a section title (numbering/case insensitive)."""
    cleaned = clean_heading_text(raw_title).lower()
    return re.sub(r'[^a-z0-9 ]+', '', cleaned).strip()


# Display cleanup is deliberately narrower than :func:`clean_heading_text`: only
# markdown markers and explicit section numbering are removed, so the wording of
# the paper's own heading is preserved.
_DISPLAY_PREFIX_PATTERNS = (
    re.compile(r'^#{1,6}\s*'),
    re.compile(r'^(?:section\s+)?\d+(?:\.\d+)*\s*[.):]\s*', re.IGNORECASE),
    re.compile(r'^(?:section\s+)?\d+(?:\.\d+)*\s+', re.IGNORECASE),
    re.compile(r'^[IVXLCD]{1,6}\s*[.):]\s*'),
    re.compile(r'^[IVXLCD]{2,6}\s+'),
)


def display_section_title(raw_title):
    """Human-facing section title with markdown markers and numbering removed."""
    title = collapse_whitespace(raw_title)
    if not title:
        return ''

    for pattern in _DISPLAY_PREFIX_PATTERNS:
        candidate = pattern.sub('', title, count=1).strip()
        if candidate and candidate != title:
            title = candidate
            break

    # Drop a leading article so "The Abstract" / "A Survey" render as "Abstract"
    # / "Survey", keeping the paper's own wording otherwise.
    title = re.sub(r'^(?:the|a|an)\s+', '', title, flags=re.IGNORECASE).strip()

    title = title.strip().strip('*_').strip()
    title = re.sub(r'\s*:\s*$', '', title).strip()
    # Title-case only when the heading was lower-cased by the article strip, so
    # existing title-case wording (e.g. "Conclusions and Future Work") is kept.
    return (title.title() if title.islower() else title) or collapse_whitespace(raw_title)


def _split_blocks_by_lines(extracted_text):
    lines = [line.strip() for line in (extracted_text or '').splitlines()]
    if not any(lines):
        return []

    blocks = []
    current = None
    for line in lines:
        if not line:
            continue

        if looks_like_section_heading(line):
            cleaned = clean_heading_text(line)
            if is_excluded_heading(cleaned):
                current = None
                continue

            concept = classify_heading(cleaned)
            if not concept and not _is_other_known_heading(cleaned.lower()):
                continue

            current = {'title': cleaned, 'concept': concept, 'lines': []}
            blocks.append(current)
            continue

        if current is not None:
            current['lines'].append(line)

    return [
        {
            'title': display_section_title(block['title']),
            'concept': block['concept'],
            'text': collapse_whitespace(' '.join(block['lines'])),
        }
        for block in blocks
    ]


# Canonical headings, longest first, used only for the single-blob fallback.
_INLINE_HEADING_CANDIDATES = tuple(
    sorted(_CANONICAL_HEADINGS, key=len, reverse=True)
)


def _is_heading_case(text):
    """True when text is ALL CAPS or Title Case, as printed section headings are.

    A leading article ("the/a/an") is ignored so "the abstract" is still treated as
    a valid title-cased heading.
    """
    normalized = re.sub(r'^(?:the|a|an)\s+', '', text, flags=re.IGNORECASE).strip()
    if not normalized:
        return False

    words = [word for word in normalized.split() if any(char.isalpha() for char in word)]
    if not words:
        return False
    if normalized.upper() == normalized:
        return True
    return all(word[0].isupper() or word.lower() in _TRAILING_FUNCTION_WORDS for word in words)


def _split_blocks_inline(extracted_text):
    """Locate canonical headings inside text that has no usable line breaks."""
    blob = collapse_whitespace(extracted_text)
    if not blob:
        return []

    matches = []
    claimed = []
    for phrase in _INLINE_HEADING_CANDIDATES:
        # Headings inside a single text blob appear at sentence boundaries
        # (e.g. "the abstract." / "results."), never as a mid-sentence word such
        # as "prior methods.", so require a sentence-boundary context.
        pattern = re.compile(
            r'(?:^|(?<=\.\s))(?:(?:the|a|an)\s+)?' + re.escape(phrase) + r'(?=\.|\s|$)',
            re.IGNORECASE | re.MULTILINE,
        )
        for match in pattern.finditer(blob):
            start, end = match.span()
            if any(start < claimed_end and claimed_start < end for claimed_start, claimed_end in claimed):
                continue
            # Case is judged on the canonical phrase itself, ignoring any leading
            # article that the optional prefix captured.
            canonical = re.sub(r'^(?:the\s+)', '', match.group(0), flags=re.IGNORECASE).strip().title()
            if not _is_heading_case(canonical):
                continue
            claimed.append((start, end))
            matches.append((start, end, match.group(0)))

    if len(matches) < 2:
        return []

    matches.sort(key=lambda item: item[0])
    blocks = []
    for position, (start, end, raw_title) in enumerate(matches):
        cleaned = clean_heading_text(raw_title)
        if is_excluded_heading(cleaned):
            continue

        concept = classify_heading(cleaned)
        if not concept and not _is_other_known_heading(cleaned.lower()):
            continue

        body_end = matches[position + 1][0] if position + 1 < len(matches) else len(blob)
        blocks.append({
            'title': display_section_title(raw_title),
            'concept': concept,
            'text': collapse_whitespace(blob[end:body_end]),
        })

    return blocks


def split_paper_blocks(extracted_text):
    """Split the paper into ordered blocks using detected section headings.

    Returns a list of ``{'title', 'concept', 'text'}`` dicts in document order.
    Back-matter (References, Acknowledgements, Appendix) is dropped. An empty
    list means no reliable heading structure was found.
    """
    blocks = _split_blocks_by_lines(extracted_text)
    if len(blocks) < 2:
        inline_blocks = _split_blocks_inline(extracted_text)
        if len(inline_blocks) > len(blocks):
            return inline_blocks
    return blocks


def detect_paper_structure(extracted_text):
    """Summarize the section structure actually present in the paper."""
    blocks = split_paper_blocks(extracted_text)
    titles = []
    concepts = set()
    for block in blocks:
        titles.append(block['title'])
        if block['concept']:
            concepts.add(block['concept'])

    return {
        'blocks': blocks,
        'titles': titles,
        'concepts': concepts,
        'has_structure': len(blocks) >= 2,
    }


def title_appears_in_paper(title, extracted_text):
    """True when the heading text itself occurs somewhere in the paper text."""
    needle = collapse_whitespace(title).lower()
    if not needle:
        return False
    haystack = collapse_whitespace(extracted_text).lower()
    return needle in haystack


def _truncate_at_word(text, limit):
    if len(text) <= limit:
        return text, False
    snippet = text[:limit]
    if ' ' in snippet:
        snippet = snippet.rsplit(' ', 1)[0]
    return snippet, True


def _head_digest(extracted_text, max_chars):
    cleaned = collapse_whitespace(extracted_text)
    snippet, truncated = _truncate_at_word(cleaned, max_chars)
    return snippet + (TRUNCATION_MARKER if truncated else '')


def build_structure_digest(extracted_text, max_chars=SECTION_DIGEST_MAX_CHARS):
    """Build a structure-aware digest covering every detected paper section.

    Each detected section contributes a labelled excerpt, so sections that appear
    late in the paper (Results, Conclusion) are visible to the AI within the same
    character budget instead of being cut off by head-only truncation.
    """
    if not extracted_text or not extracted_text.strip():
        return ''

    blocks = [block for block in split_paper_blocks(extracted_text) if block['text']]
    if not blocks:
        return _head_digest(extracted_text, max_chars)

    weights = [3 if block['concept'] else 1 for block in blocks]
    total_weight = sum(weights) or 1
    label_overhead = sum(len(block['title']) + 6 for block in blocks)
    text_budget = max(max_chars - label_overhead, SECTION_DIGEST_MIN_EXCERPT * len(blocks))

    truncated_any = False
    parts = []
    for block, weight in zip(blocks, weights):
        share = int(text_budget * weight / total_weight)
        limit = max(SECTION_DIGEST_MIN_EXCERPT, min(SECTION_DIGEST_MAX_EXCERPT, share))
        excerpt, truncated = _truncate_at_word(block['text'], limit)
        truncated_any = truncated_any or truncated
        parts.append(f'## {block["title"]}\n{excerpt}')

    digest = '\n\n'.join(parts)
    if len(digest) > max_chars:
        digest, _ = _truncate_at_word(digest, max_chars)
        truncated_any = True

    return digest + (TRUNCATION_MARKER if truncated_any else '')
