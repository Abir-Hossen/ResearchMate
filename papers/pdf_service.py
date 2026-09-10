import re
import unicodedata
from datetime import datetime
from io import BytesIO

from django.http import HttpResponse
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm, inch, mm
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    ListFlowable,
    ListItem,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

MARGIN = 50
PAGE_WIDTH, PAGE_HEIGHT = A4
CONTENT_WIDTH = PAGE_WIDTH - 2 * MARGIN


def sanitize_filename(text):
    if not text:
        return 'document'
    sanitized = re.sub(r'[\\/:*?"<>|]', '_', text)
    sanitized = re.sub(r'\s+', '_', sanitized)
    sanitized = sanitized.strip('._')
    if len(sanitized) > 100:
        sanitized = sanitized[:100].rstrip('._')
    return sanitized or 'document'


def clean_text(text):
    """Normalize Unicode text to handle PDF extraction artifacts like ligatures and special dashes."""
    if not text:
        return ''
    # Normalize Unicode (NFKD decomposes some ligatures)
    text = unicodedata.normalize('NFKD', text)
    # Replace common PDF extraction artifacts using translate for simultaneous replacement
    # (avoids double-replacement issues where fi matches inside ffi)
    replacements = {
        # Ligatures (Alphabetic Presentation Forms) - handle before NFKD issues
        '\ufb03': 'ffi',  # ffi ligature
        '\ufb04': 'ffl',  # ffl ligature
        '\ufb00': 'ff',   # ff ligature
        '\ufb01': 'fi',   # fi ligature
        '\ufb02': 'fl',   # fl ligature
        '\ufb05': 'ft',   # ft ligature
        '\ufb06': 'st',   # st ligature
        # Dashes and hyphens
        '\u2010': '-',    # hyphen
        '\u2011': '-',    # non-breaking hyphen
        '\u2012': '-',    # figure dash
        '\u2013': '-',    # en dash
        '\u2014': '-',    # em dash
        '\u2015': '-',    # horizontal bar
        '\u2212': '-',    # minus sign
        # Quotes
        '\u2018': "'",    # left single quote
        '\u2019': "'",    # right single quote
        '\u201c': '"',    # left double quote
        '\u201d': '"',    # right double quote
        # Other
        '\u2026': '...',  # ellipsis
        '\u00a0': ' ',    # non-breaking space
        '\u200b': '',     # zero width space
        '\u200c': '',     # zero width non-joiner
        '\u200d': '',     # zero width joiner
        '\ufeff': '',     # zero width no-break space (BOM)
        # Black squares/bullets - replace with space to separate words
        '\u25aa': ' ',    # black small square (■)
        '\u25a0': ' ',    # black square
        '\u25cf': ' ',    # black circle
        '\u2022': ' ',    # bullet
        '\u25e6': ' ',    # white bullet
        '\u2043': ' ',    # hyphen bullet
    }
    # Use translate for simultaneous replacement (avoids double-replacement issues)
    translation_table = str.maketrans(replacements)
    text = text.translate(translation_table)
    # Remove any remaining non-printable control characters except newlines/tabs
    text = ''.join(ch for ch in text if ch == '\n' or ch == '\t' or ch == '\r' or ord(ch) >= 32)
    return text


def get_styles():
    styles = getSampleStyleSheet()

    styles.add(ParagraphStyle(
        name='RM_Title',
        fontName='Helvetica-Bold',
        fontSize=16,
        leading=20,
        alignment=TA_LEFT,
        textColor=HexColor('#0d3b66'),
        spaceAfter=6,
    ))

    styles.add(ParagraphStyle(
        name='RM_FeatureTitle',
        fontName='Helvetica-Bold',
        fontSize=13,
        leading=16,
        alignment=TA_LEFT,
        textColor=HexColor('#17324d'),
        spaceAfter=4,
    ))

    styles.add(ParagraphStyle(
        name='RM_Subtitle',
        fontName='Helvetica',
        fontSize=9,
        leading=12,
        alignment=TA_LEFT,
        textColor=HexColor('#5f6b7a'),
        spaceAfter=16,
    ))

    styles.add(ParagraphStyle(
        name='RM_Heading1',
        fontName='Helvetica-Bold',
        fontSize=14,
        leading=18,
        alignment=TA_LEFT,
        textColor=HexColor('#0d3b66'),
        spaceBefore=18,
        spaceAfter=10,
        borderWidth=0,
        borderPadding=0,
        borderColor=HexColor('#dbeafe'),
    ))

    styles.add(ParagraphStyle(
        name='RM_Heading2',
        fontName='Helvetica-Bold',
        fontSize=12,
        leading=15,
        alignment=TA_LEFT,
        textColor=HexColor('#0d3b66'),
        spaceBefore=14,
        spaceAfter=8,
    ))

    styles.add(ParagraphStyle(
        name='RM_Heading3',
        fontName='Helvetica-Bold',
        fontSize=11,
        leading=14,
        alignment=TA_LEFT,
        textColor=HexColor('#17324d'),
        spaceBefore=12,
        spaceAfter=6,
    ))

    styles.add(ParagraphStyle(
        name='RM_Body',
        fontName='Helvetica',
        fontSize=10,
        leading=14,
        alignment=TA_JUSTIFY,
        textColor=HexColor('#1f2937'),
        spaceAfter=8,
        firstLineIndent=0,
    ))

    styles.add(ParagraphStyle(
        name='RM_Bullet',
        fontName='Helvetica',
        fontSize=10,
        leading=14,
        alignment=TA_LEFT,
        textColor=HexColor('#1f2937'),
        spaceAfter=4,
        leftIndent=24,
        bulletIndent=12,
        firstLineIndent=0,
    ))

    styles.add(ParagraphStyle(
        name='RM_Numbered',
        fontName='Helvetica',
        fontSize=10,
        leading=14,
        alignment=TA_LEFT,
        textColor=HexColor('#1f2937'),
        spaceAfter=4,
        leftIndent=24,
        bulletIndent=12,
        firstLineIndent=0,
    ))

    styles.add(ParagraphStyle(
        name='RM_Label',
        fontName='Helvetica-Bold',
        fontSize=9,
        leading=12,
        alignment=TA_LEFT,
        textColor=HexColor('#5f6b7a'),
        spaceAfter=2,
    ))

    styles.add(ParagraphStyle(
        name='RM_Value',
        fontName='Helvetica',
        fontSize=10,
        leading=14,
        alignment=TA_JUSTIFY,
        textColor=HexColor('#1f2937'),
        spaceAfter=6,
        leftIndent=12,
    ))

    styles.add(ParagraphStyle(
        name='RM_Footer',
        fontName='Helvetica',
        fontSize=8,
        leading=10,
        alignment=TA_LEFT,
        textColor=HexColor('#9ca3af'),
        spaceAfter=0,
    ))

    styles.add(ParagraphStyle(
        name='RM_CodeInline',
        fontName='Courier',
        fontSize=9,
        leading=12,
        alignment=TA_LEFT,
        textColor=HexColor('#374151'),
    ))

    return styles


def escape_html(text):
    if not text:
        return ''
    return (
        text.replace('&', '&')
        .replace('<', '<')
        .replace('>', '>')
    )


def format_inline(text):
    if not text:
        return ''
    text = escape_html(text)
    text = clean_text(text)
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'\*(.+?)\*', r'<i>\1</i>', text)
    # Inline code: use ReportLab-supported font tag
    text = re.sub(r'`([^`]+)`', r'<font face="Courier" color="#374151" size="9">\1</font>', text)
    return text


def parse_markdown_to_flowables(markdown_text, styles):
    if not markdown_text:
        return []

    flowables = []
    lines = [line.rstrip() for line in markdown_text.splitlines()]
    paragraph_buffer = []
    list_items = []
    list_type = None

    def flush_paragraph():
        nonlocal paragraph_buffer
        if paragraph_buffer:
            paragraph_text = ' '.join(part.strip() for part in paragraph_buffer if part.strip())
            if paragraph_text:
                flowables.append(Paragraph(format_inline(paragraph_text), styles['RM_Body']))
            paragraph_buffer = []

    def flush_list():
        nonlocal list_items, list_type
        if list_items:
            bullet_type = 'bullet' if list_type == 'bullet' else '1'
            flowables.append(ListFlowable(
                [ListItem(Paragraph(format_inline(item), styles['RM_Bullet' if list_type == 'bullet' else 'RM_Numbered'])) for item in list_items],
                bulletType=bullet_type,
                start='1' if list_type == 'numbered' else None,
                leftIndent=24,
                bulletFontName='Helvetica' if list_type == 'bullet' else 'Helvetica',
                bulletFontSize=10,
            ))
            list_items = []
            list_type = None

    for line in lines:
        stripped = line.strip()
        if not stripped:
            flush_paragraph()
            flush_list()
            continue

        if stripped.startswith('## '):
            flush_paragraph()
            flush_list()
            flowables.append(Paragraph(format_inline(stripped[3:].strip()), styles['RM_Heading1']))
            continue

        if stripped.startswith('### '):
            flush_paragraph()
            flush_list()
            flowables.append(Paragraph(format_inline(stripped[4:].strip()), styles['RM_Heading2']))
            continue

        if stripped.startswith('# '):
            flush_paragraph()
            flush_list()
            flowables.append(Paragraph(format_inline(stripped[2:].strip()), styles['RM_Heading1']))
            continue

        if stripped.startswith('- ') or stripped.startswith('* '):
            flush_paragraph()
            if list_type != 'bullet':
                flush_list()
                list_type = 'bullet'
            list_items.append(stripped[2:].strip())
            continue

        if re.match(r'^\d+\.\s', stripped):
            flush_paragraph()
            if list_type != 'numbered':
                flush_list()
                list_type = 'numbered'
            list_items.append(re.sub(r'^\d+\.\s*', '', stripped).strip())
            continue

        paragraph_buffer.append(stripped)

    flush_paragraph()
    flush_list()

    return flowables


def build_document_header(styles, paper_title, feature_title):
    elements = []
    elements.append(Paragraph('ResearchMate', styles['RM_Title']))
    elements.append(Paragraph(clean_text(escape_html(paper_title)), styles['RM_Title']))
    elements.append(Spacer(1, 4))
    elements.append(HRFlowable(width='100%', thickness=1, color=HexColor('#dbeafe'), spaceAfter=8, spaceBefore=0))
    elements.append(Paragraph(feature_title, styles['RM_FeatureTitle']))
    elements.append(Spacer(1, 4))
    elements.append(Paragraph(f'Generated on {datetime.now().strftime("%B %d, %Y")}', styles['RM_Subtitle']))
    elements.append(HRFlowable(width='100%', thickness=0.5, color=HexColor('#e5e7eb'), spaceAfter=12, spaceBefore=4))
    return elements


def add_page_number(canvas, doc):
    page_num = canvas.getPageNumber()
    text = f'ResearchMate | Page {page_num}'
    canvas.saveState()
    canvas.setFont('Helvetica', 8)
    canvas.setFillColor(HexColor('#9ca3af'))
    canvas.drawString(MARGIN, 30, text)
    canvas.restoreState()


def generate_pdf_response(elements, filename):
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=MARGIN + 20,
        title='ResearchMate Export',
        author='ResearchMate',
    )
    doc.build(elements, onFirstPage=add_page_number, onLaterPages=add_page_number)
    buffer.seek(0)
    response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


def generate_beginner_pdf(paper, analysis):
    styles = get_styles()
    elements = []

    if not analysis or not analysis.beginner_explanation:
        return None

    elements.extend(build_document_header(styles, paper.title, 'Beginner Explanation'))

    # Only include the main beginner explanation content, not extra metadata
    content_flowables = parse_markdown_to_flowables(analysis.beginner_explanation, styles)
    elements.extend(content_flowables)

    filename = f'ResearchMate_Beginner_Explanation_{sanitize_filename(paper.title)}.pdf'
    return generate_pdf_response(elements, filename)


def generate_technical_pdf(paper, analysis):
    styles = get_styles()
    elements = []

    if not analysis or not analysis.technical_explanation:
        return None

    elements.extend(build_document_header(styles, paper.title, 'Technical Explanation'))

    content_flowables = parse_markdown_to_flowables(analysis.technical_explanation, styles)
    elements.extend(content_flowables)

    filename = f'ResearchMate_Technical_Explanation_{sanitize_filename(paper.title)}.pdf'
    return generate_pdf_response(elements, filename)


def generate_glossary_pdf(paper):
    styles = get_styles()
    elements = []

    glossary_terms = list(paper.glossary_terms.all().order_by('display_order', 'id'))
    if not glossary_terms:
        return None

    elements.extend(build_document_header(styles, paper.title, 'Glossary'))

    for idx, term in enumerate(glossary_terms, 1):
        term_elements = []

        term_elements.append(Paragraph(f'{idx}. {clean_text(escape_html(term.term))}', styles['RM_Heading2']))

        explanation = term.explanation or term.technical_explanation or term.simple_explanation
        if explanation:
            term_elements.append(Paragraph('<b>Explanation:</b>', styles['RM_Label']))
            term_elements.append(Paragraph(format_inline(explanation), styles['RM_Value']))

        if term.paper_role:
            term_elements.append(Paragraph('<b>Role in This Paper:</b>', styles['RM_Label']))
            term_elements.append(Paragraph(format_inline(term.paper_role), styles['RM_Value']))

        if term.simple_explanation and term.simple_explanation != (term.explanation or term.technical_explanation):
            term_elements.append(Paragraph('<b>Simple Explanation:</b>', styles['RM_Label']))
            term_elements.append(Paragraph(format_inline(term.simple_explanation), styles['RM_Value']))

        if term.technical_explanation and term.technical_explanation != (term.explanation or term.simple_explanation):
            term_elements.append(Paragraph('<b>Technical Explanation:</b>', styles['RM_Label']))
            term_elements.append(Paragraph(format_inline(term.technical_explanation), styles['RM_Value']))

        if term.example:
            term_elements.append(Paragraph('<b>Example:</b>', styles['RM_Label']))
            term_elements.append(Paragraph(format_inline(term.example), styles['RM_Value']))

        if idx < len(glossary_terms):
            term_elements.append(Spacer(1, 8))
            term_elements.append(HRFlowable(width='100%', thickness=0.3, color=HexColor('#e5e7eb'), spaceAfter=8, spaceBefore=4))

        elements.append(KeepTogether(term_elements))

    filename = f'ResearchMate_Glossary_{sanitize_filename(paper.title)}.pdf'
    return generate_pdf_response(elements, filename)


def generate_viva_pdf(paper):
    styles = get_styles()
    elements = []

    viva_questions = list(paper.viva_questions.all().order_by('display_order', 'id'))
    if not viva_questions:
        return None

    elements.extend(build_document_header(styles, paper.title, 'Viva Preparation'))

    grouped = {}
    for q in viva_questions:
        cat = q.category or 'General'
        grouped.setdefault(cat, []).append(q)

    first_category = True
    for category_name, questions in grouped.items():
        if not first_category:
            elements.append(PageBreak())
        first_category = False

        elements.append(Paragraph(f'Category: {clean_text(escape_html(category_name))}', styles['RM_Heading1']))
        elements.append(Spacer(1, 6))

        for q_idx, q in enumerate(questions, 1):
            q_elements = []

            q_elements.append(Paragraph(f'Question {q_idx}: {clean_text(escape_html(q.question))}', styles['RM_Heading2']))

            if q.suggested_answer:
                q_elements.append(Paragraph('<b>Suggested Answer:</b>', styles['RM_Label']))
                q_elements.append(Paragraph(format_inline(q.suggested_answer), styles['RM_Value']))

            if q.follow_up_question:
                q_elements.append(Paragraph('<b>Follow-up Question:</b>', styles['RM_Label']))
                q_elements.append(Paragraph(format_inline(q.follow_up_question), styles['RM_Value']))

            if q.examiner_tip:
                q_elements.append(Paragraph('<b>Examiner Tip:</b>', styles['RM_Label']))
                q_elements.append(Paragraph(format_inline(q.examiner_tip), styles['RM_Value']))

            diff = q.difficulty or 'Medium'
            q_elements.append(Paragraph(f'<b>Difficulty:</b> {clean_text(escape_html(diff))}', styles['RM_Label']))

            if q_idx < len(questions):
                q_elements.append(Spacer(1, 8))
                q_elements.append(HRFlowable(width='100%', thickness=0.3, color=HexColor('#e5e7eb'), spaceAfter=8, spaceBefore=4))

            elements.append(KeepTogether(q_elements))

    filename = f'ResearchMate_Viva_Preparation_{sanitize_filename(paper.title)}.pdf'
    return generate_pdf_response(elements, filename)


def generate_revision_notes_pdf(paper, analysis):
    styles = get_styles()
    elements = []

    if not analysis or not analysis.revision_notes:
        return None

    elements.extend(build_document_header(styles, paper.title, 'Revision Notes'))

    content_flowables = parse_markdown_to_flowables(analysis.revision_notes, styles)
    elements.extend(content_flowables)

    filename = f'ResearchMate_Revision_Notes_{sanitize_filename(paper.title)}.pdf'
    return generate_pdf_response(elements, filename)