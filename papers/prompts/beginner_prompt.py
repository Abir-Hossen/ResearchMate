from __future__ import annotations


def build_beginner_prompt_text(extracted_text):
    compact_text = extracted_text[:5500] if extracted_text else ''
    
    return f"""You are a university professor explaining a research paper to a beginner student.

Assume the student has no background knowledge. Teach the paper clearly and progressively using ONLY the provided paper text. Do not use generic knowledge outside the paper.

Return ONLY valid JSON with this schema:
{{
  "beginner_explanation": "Paper-specific beginner-friendly explanation.",
  "key_contributions": ["Contribution 1", "Contribution 2", "Contribution 3"],
  "key_concepts": ["Concept 1", "Concept 2", "Concept 3"],
  "reading_difficulty": {{"level": "Beginner/Intermediate/Advanced", "reason": "Brief reason"}}
}}

Structure the beginner_explanation with these exact headings (600-800 words total):
## What the Paper Is About
[Based on the paper]

## Why the Research Matters
[Based on the paper]

## Main Idea / Method
[Based on the paper]

## Key Findings or Contributions
[Based on the paper]

## Simple Explanation of the Core Concepts
[Based on the paper]

## Key Takeaway
[Based on the paper]

CRITICAL CONSTRAINTS:
- Use ONLY the provided paper text. Do not add generic knowledge.
- Keep language simple and clear
- Do NOT generate technical explanation, glossary, flashcards, quiz questions, viva questions, or revision notes

Paper text:
{compact_text}

Return ONLY the JSON object. No preamble, markdown, or code fences.
"""
