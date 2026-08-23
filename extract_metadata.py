#!/usr/bin/env python
"""Extract complete response metadata from the failed Beginner request."""

import os
import django
import json

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ResearchMate.settings')
django.setup()

from papers.models import AIAnalysis

latest = AIAnalysis.objects.order_by('-id').first()

if latest:
    print("=" * 80)
    print("RESPONSE METADATA FROM FAILED BEGINNER REQUEST")
    print("=" * 80)
    
    # Get the raw response object details
    print(f"\nDatabase Record Fields:")
    print(f"  Paper ID: {latest.paper_id}")
    print(f"  Analysis Status: {latest.analysis_status}")
    print(f"  AI Model: {latest.ai_model}")
    print(f"  Generated At: {latest.generated_at}")
    print(f"  Last Updated: {latest.last_updated}")
    print(f"  Raw Response Length: {len(latest.raw_response or '')}")
    
    print(f"\nAnalysis Error:")
    print(f"  {latest.analysis_error}")
    
    # Try to parse the raw_response as a string to see what was actually sent back
    raw = latest.raw_response or ''
    
    # Check for response structure indicators
    if 'finish_reason' in raw:
        # Extract finish_reason if it's in there
        import re
        match = re.search(r'"finish_reason"\s*:\s*"([^"]+)"', raw)
        if match:
            print(f"\nFinish Reason: {match.group(1)}")
    
    # Check for usage information in the raw response
    if '"usage"' in raw or '"prompt_tokens"' in raw:
        print("\nUsage information appears to be in raw_response (embedded in JSON)")
    
    print(f"\nRaw Response Truncation:")
    print(f"  Total characters: {len(raw)}")
    print(f"  Ends with: ...{repr(raw[-80:])}")
    print(f"  Last 200 chars:\n{repr(raw[-200:])}")
    
else:
    print("No records found.")
