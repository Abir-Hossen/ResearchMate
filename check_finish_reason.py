#!/usr/bin/env python
"""
Check if the response object was logged and extract finish_reason,
or attempt to replicate the request to get the actual response.
"""

import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ResearchMate.settings')
django.setup()

from django.conf import settings
from groq import Groq
from papers.models import Paper, PaperContent
import logging

print("=" * 80)
print("CHECKING FOR FINISH_REASON IN LOGS")
print("=" * 80)

# Set up logging to see what was captured
logging.basicConfig(level=logging.DEBUG)

# Get the paper that failed
paper = Paper.objects.get(id=67)
try:
    content = paper.content
except PaperContent.DoesNotExist:
    content = None

if paper and content:
    print(f"\nPaper: {paper.title}")
    print(f"Content extracted_text length: {len(content.extracted_text)}")
    
    # Now make a test request to see what finish_reason we get
    print("\nAttempting to extract finish_reason from test request...")
    print("(Using same model and prompt as failed request)")
    
    try:
        client = Groq(api_key=settings.GROQ_API_KEY)
        
        # Create a simple test prompt
        test_prompt = "Return exactly this JSON: {\"test\": \"value\"}"
        
        response = client.chat.completions.create(
            model='openai/gpt-oss-120b',
            messages=[{'role': 'user', 'content': test_prompt}],
            temperature=0.0,
        )
        
        print("\nTest Request Response Details:")
        print(f"  finish_reason: {response.choices[0].finish_reason}")
        print(f"  stop_reason: {getattr(response.choices[0], 'stop_reason', 'N/A')}")
        print(f"  prompt_tokens: {response.usage.prompt_tokens}")
        print(f"  completion_tokens: {response.usage.completion_tokens}")
        
        # Now try with a longer, more complex response
        print("\n" + "-" * 80)
        print("Testing with longer response requirement...")
        
        from papers.ai_service import AIService
        from papers.provider_factory import ProviderFactory
        
        provider = ProviderFactory.create_provider()
        ai_service = AIService(provider=provider)
        
        # Build the actual beginner prompt
        prompt = ai_service.build_prompt('beginner', content.extracted_text[:500])
        
        response2 = client.chat.completions.create(
            model='openai/gpt-oss-120b',
            messages=[{'role': 'user', 'content': prompt}],
            temperature=0.0,
        )
        
        print(f"\nBeginner Prompt Test Response:")
        print(f"  finish_reason: {response2.choices[0].finish_reason}")
        print(f"  prompt_tokens: {response2.usage.prompt_tokens}")
        print(f"  completion_tokens: {response2.usage.completion_tokens}")
        print(f"  response length: {len(response2.choices[0].message.content)}")
        
        if response2.choices[0].finish_reason == 'length':
            print("\n  ⚠️  FINISH_REASON='length' → Response was TRUNCATED due to token limit!")
        
    except Exception as e:
        print(f"Error during test: {e}")
else:
    print("Paper not found")
