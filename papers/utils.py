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

    parts = []
    lines = content.splitlines()

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith('## '):
            heading = stripped[3:].strip()
            parts.append(f'<h2 class="section-title">{heading}</h2>')
        elif stripped.startswith('- '):
            parts.append(f'<li>{stripped[2:].strip()}</li>')
        elif stripped.startswith('* '):
            parts.append(f'<li>{stripped[2:].strip()}</li>')
        elif stripped.startswith('1. '):
            parts.append(f'<li>{stripped[3:].strip()}</li>')
        else:
            parts.append(f'<p>{stripped}</p>')

    if not parts:
        return ''

    html = []
    in_list = False
    for chunk in parts:
        if chunk.startswith('<li>'):
            if not in_list:
                html.append('<ul class="section-list">')
                in_list = True
            html.append(chunk)
        else:
            if in_list:
                html.append('</ul>')
                in_list = False
            html.append(chunk)

    if in_list:
        html.append('</ul>')

    return '\n'.join(html)
