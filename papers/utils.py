import os
import re


def format_file_size(size_bytes):
    if size_bytes is None:
        return '0 B'

    units = ['B', 'KB', 'MB', 'GB']
    size = float(size_bytes)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f'{size:.1f} {unit}' if unit != 'B' else f'{int(size)} {unit}'
        size /= 1024


def render_beginner_markdown(content):
    if not content:
        return ''

    lines = [line.rstrip() for line in content.splitlines()]
    html = []
    paragraph_buffer = []
    list_buffer = []

    def flush_paragraph():
        if paragraph_buffer:
            paragraph_text = ' '.join(part.strip() for part in paragraph_buffer if part.strip())
            if paragraph_text:
                html.append(f'<p>{paragraph_text}</p>')
            paragraph_buffer.clear()

    def flush_list():
        if list_buffer:
            html.append('<ul class="section-list">')
            for item in list_buffer:
                html.append(f'<li>{item}</li>')
            html.append('</ul>')
            list_buffer.clear()

    for line in lines:
        stripped = line.strip()
        if not stripped:
            flush_paragraph()
            continue

        if stripped.startswith('## '):
            flush_paragraph()
            flush_list()
            html.append(f'<h2 class="section-title">{stripped[3:].strip()}</h2>')
            continue

        if stripped.startswith('### '):
            flush_paragraph()
            flush_list()
            html.append(f'<h3 class="subsection-title">{stripped[4:].strip()}</h3>')
            continue

        if stripped.startswith('- ') or stripped.startswith('* ') or stripped.startswith('1. '):
            flush_paragraph()
            if stripped.startswith('1. '):
                list_buffer.append(stripped[3:].strip())
            else:
                list_buffer.append(stripped[2:].strip())
            continue

        paragraph_buffer.append(stripped)

    flush_paragraph()
    flush_list()

    return '\n'.join(html)
