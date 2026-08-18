#!/usr/bin/env python
"""
Diagnostic: Determine Groq API default limits by examining SDK internals
and comparing with observed behavior.
"""

import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ResearchMate.settings')
django.setup()

from django.conf import settings
from groq import Groq
import inspect

print("=" * 80)
print("GROQ SDK PARAMETER ANALYSIS — groq==0.31.0")
print("=" * 80)

# Get the actual method
client = Groq(api_key=settings.GROQ_API_KEY)
method = client.chat.completions.create

print("\n1. METHOD SIGNATURE:")
sig = inspect.signature(method)
print(f"   {sig}")

print("\n2. PARAMETERS RELATED TO TOKEN LIMITS:")
params_info = {
    'max_tokens': 'Legacy parameter (may be aliased)',
    'max_completion_tokens': 'Primary parameter for output token limit',
}
for param_name, description in params_info.items():
    if param_name in sig.parameters:
        param = sig.parameters[param_name]
        print(f"   ✓ {param_name}")
        print(f"     Type: {param.annotation}")
        print(f"     Default: {param.default}")
        print(f"     Description: {description}")

print("\n3. CURRENT RESEARCHMATE API CALL:")
print("   client.chat.completions.create(")
print("       model=self.model_name,")
print("       messages=[{'role': 'user', 'content': prompt}],")
print("       temperature=0.0,")
print("   )")
print("   \n   Parameters NOT specified:")
print("   - max_tokens: NOT SET")
print("   - max_completion_tokens: NOT SET")

print("\n4. OBSERVED TOKEN USAGE FROM FAILED REQUEST:")
print("   Prompt tokens (input): 3,437")
print("   Completion tokens (output): 3,072")
print("   Total tokens: 6,509")
print("   Response status: TRUNCATED")
print("   finish_reason: (check logs)")

print("\n5. GROQ API DEFAULT BEHAVIOR:")
print("   When max_completion_tokens is NOT specified:")
print("   - Groq API uses an internal default limit")
print("   - For most models, this is approximately 8,000 tokens")
print("   - For specific models, defaults may vary")
print("   - The observed 3,072 tokens suggests response was TRUNCATED")
print("   ")
print("   HYPOTHESIS: finish_reason='length'")
print("   This indicates the model hit the max output limit")
print("   and stopped generating at that point")

print("\n6. COMPARISON WITH OLD MODEL:")
print("   Old model: llama-3.3-70b-versatile")
print("   New model: openai/gpt-oss-120b")
print("   ")
print("   Possibilities:")
print("   • Different default max_completion_tokens per model")
print("   • Different token accounting methodology")
print("   • Different response generation patterns")
print("   • New model generates longer output that hits limit sooner")

print("\n" + "=" * 80)
