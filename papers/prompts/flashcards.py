def build_flashcards_prompt(extracted_text):
    template = """You are generating paper-specific active recall flashcards for a research paper.
Focus only on the concepts, methods, data, evaluation, results, and contributions that actually appear in this paper.
Do not create glossary definitions, high-level summaries, or generic textbook questions.
Each flashcard must test understanding of an important idea from this paper.

Return ONLY valid JSON.
Do NOT include markdown, code fences, explanations, introductory text, comments, or natural-language prose outside the JSON.
Return ONLY one valid JSON object.

Use this schema exactly:
{{
  "flashcards": [
    {{
      "question": "string",
      "answer": "string",
      "paper_context": "string",
      "importance": ["string"],
      "category": "string",
      "difficulty": "string"
    }}
  ]
}}

Generate approximately 10-15 flashcards.
Each question should be paper-specific and draw directly from concepts in the paper text.
Each answer should be concise, 2-4 sentences, and explain the concept in your own words.
"importance" should list 1-3 reasons why this flashcard matters for understanding the paper.
"category" must be one of: Research Problem, Methodology, Algorithm, Architecture, Dataset, Evaluation, Results, Limitation, Contribution.
"difficulty" must be one of: Easy, Medium, Hard.

Paper text:
{extracted_text}
"""
    return template.format(extracted_text=extracted_text[:12000])
