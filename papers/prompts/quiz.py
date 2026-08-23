def build_quiz_prompt(extracted_text):
    return f"""Return ONLY valid JSON. No markdown, no code fences, no extra text.

Generate exactly 10 paper-specific quiz questions from the paper text below.

JSON rules:
- Use ONLY double quotes for keys and string values.
- Escape any double quote inside a string as \\".
- Do NOT include literal newlines inside JSON string values.
- Every object in quiz_questions must have exactly these keys: question, options, correct_answer, explanation, difficulty.
- options must be an array of exactly 4 strings.
- correct_answer must exactly match one of the 4 option strings.
- difficulty must be Easy, Medium, or Hard.
- explanation must be 1-2 sentences.

Schema:
{{
  "quiz_questions": [
    {{
      "question": "string",
      "options": ["string", "string", "string", "string"],
      "correct_answer": "string",
      "explanation": "string",
      "difficulty": "Easy"
    }}
  ]
}}

Paper text:
{extracted_text}
"""
