#!/usr/bin/env python
"""Check the latest AIAnalysis error for debugging."""

import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ResearchMate.settings')
django.setup()

from papers.models import AIAnalysis

# Get the most recent AIAnalysis
latest = AIAnalysis.objects.order_by('-id').first()

if latest:
    print("=" * 80)
    print("LATEST AIANALYSIS RECORD")
    print("=" * 80)
    print(f"Paper ID: {latest.paper_id}")
    print(f"Analysis Status: {latest.analysis_status}")
    print(f"AI Model: {latest.ai_model}")
    print(f"Analysis Error: {latest.analysis_error}")
    print(f"\nRaw Response (first 500 chars):")
    print(f"{(latest.raw_response or '')[:500]}")
    print("\n" + "=" * 80)
else:
    print("No AIAnalysis records found.")
