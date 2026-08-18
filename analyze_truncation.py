#!/usr/bin/env python
"""Analyze the truncated JSON response to understand what's missing."""

import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ResearchMate.settings')
django.setup()

from papers.models import AIAnalysis

latest = AIAnalysis.objects.order_by('-id').first()

if latest and latest.raw_response:
    raw = latest.raw_response
    
    print("=" * 80)
    print("RESPONSE TRUNCATION ANALYSIS")
    print("=" * 80)
    
    # Find all top-level keys that are complete
    import re
    
    # Count brackets and braces
    open_braces = raw.count('{')
    close_braces = raw.count('}')
    open_brackets = raw.count('[')
    close_brackets = raw.count(']')
    
    print(f"\nStructural Balance:")
    print(f"  Braces: {open_braces} open, {close_braces} close (balanced: {open_braces == close_braces})")
    print(f"  Brackets: {open_brackets} open, {close_brackets} close (balanced: {open_brackets == close_brackets})")
    
    # Count fields
    fields_with_data = []
    for field in ['beginner_explanation', 'technical_explanation', 'key_contributions', 'key_concepts', 'reading_difficulty', 'glossary', 'flashcards', 'quiz_questions', 'viva_questions', 'revision_notes']:
        if f'"{field}"' in raw:
            fields_with_data.append(field)
    
    print(f"\nFields found in response:")
    for field in fields_with_data:
        print(f"  ✓ {field}")
    
    print(f"\nResponse Status:")
    print(f"  Total length: {len(raw)} characters")
    print(f"  Ends with: ...{repr(raw[-100:])}")
    print(f"\nLikely Issue:")
    print(f"  The response is TRUNCATED (ends with unterminated string)")
    print(f"  This suggests max_tokens limit was reached")
    print(f"  The model may have different token limits than the old model")
else:
    print("No raw response found.")
