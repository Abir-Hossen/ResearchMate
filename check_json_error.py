#!/usr/bin/env python
"""Get the full raw response to identify JSON formatting issue."""

import os
import django
import json

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ResearchMate.settings')
django.setup()

from papers.models import AIAnalysis

latest = AIAnalysis.objects.order_by('-id').first()

if latest and latest.raw_response:
    raw = latest.raw_response
    print("=" * 80)
    print("FULL RAW RESPONSE LENGTH:", len(raw))
    print("=" * 80)
    
    # Try to find where the JSON breaks
    try:
        json.loads(raw)
        print("JSON is valid!")
    except json.JSONDecodeError as e:
        print(f"JSON Parsing Error:")
        print(f"  Error: {e.msg}")
        print(f"  Line: {e.lineno}")
        print(f"  Column: {e.colno}")
        print(f"  Char position: {e.pos}")
        
        # Show context around the error
        lines = raw.split('\n')
        error_line = e.lineno - 1
        
        print(f"\nContext around error (lines {max(0, error_line-2)} to {min(len(lines)-1, error_line+2)}):")
        for i in range(max(0, error_line-2), min(len(lines), error_line+3)):
            marker = ">>> " if i == error_line else "    "
            print(f"{marker}Line {i+1}: {lines[i][:120]}")
        
        print(f"\nCharacter context around position {e.pos}:")
        start = max(0, e.pos - 50)
        end = min(len(raw), e.pos + 50)
        print(f"...{repr(raw[start:end])}...")
        print(f"     {' ' * (e.pos - start)}^--- Error here")
else:
    print("No raw response found.")
