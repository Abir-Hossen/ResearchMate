import os


def format_file_size(size_bytes):
    if size_bytes is None:
        return '0 B'

    units = ['B', 'KB', 'MB', 'GB']
    size = float(size_bytes)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f'{size:.1f} {unit}' if unit != 'B' else f'{int(size)} {unit}'
        size /= 1024
