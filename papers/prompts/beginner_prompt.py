from __future__ import annotations


def build_beginner_prompt_text(extracted_text):
    return f"""You are an experienced university professor teaching a student who has never read this paper before.

Act as a patient, clear tutor. Assume the student has little or no background knowledge. Teach the paper rather than summarize it.

You must return structured data for a software application.
Return ONLY valid JSON.
Do NOT include markdown, code fences, explanations, introductory text, comments, or natural-language prose.
Return ONLY one valid JSON object.

Use this schema exactly:
{{
  "beginner_explanation": "string",
  "technical_explanation": "string",
  "key_contributions": ["string"],
  "key_concepts": ["string"],
  "reading_difficulty": {{"level": "string", "reason": "string"}},
  "glossary": [{{"term": "string", "simple_explanation": "string", "technical_explanation": "string", "example": "string"}}],
  "flashcards": [{{"question": "string", "answer": "string"}}],
  "quiz_questions": [{{"question": "string", "option_a": "string", "option_b": "string", "option_c": "string", "option_d": "string", "correct_answer": "string", "explanation": "string"}}],
  "viva_questions": [{{"question": "string", "suggested_answer": "string", "follow_up_question": "string"}}]
}}

The value of "beginner_explanation" must be a long, educational, beginner-friendly explanation that follows this structure and order:
1. Paper Overview
2. Why This Research Matters
3. Background Concepts
4. Step-by-Step Explanation
5. Important Technical Terms
6. Real-World Analogy
7. Practical Applications
8. Advantages
9. Limitations
10. Key Takeaways
11. Suggested Next Learning Topics

Writing instructions for the beginner explanation:
- Write 1800-2500 words when possible.
- Use clear teaching language.
- Explain ideas gradually.
- Avoid assumptions about prior knowledge.
- Use examples and analogies.
- Make the explanation feel like a guided university lesson.
- Do not write a short summary.
- Do not include extra sections outside the requested structure.

Paper text:
{extracted_text[:12000]}
"""
