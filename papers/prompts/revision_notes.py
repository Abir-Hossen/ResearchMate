def build_revision_notes_prompt(extracted_text):
    return f"""You are generating concise revision notes for a student studying a research paper.

Write the notes in Markdown using ONLY the provided paper text. Do not invent facts.

Use exactly these sections and formatting:

## Problem They Solve
Write 2-3 bullet points describing the specific problem or gap the paper addresses.

## Models / Methods Used
Write 2-3 bullet points naming the actual models, algorithms, or methods proposed or used in the paper.

## Dataset
Write 2-3 bullet points about the dataset(s) used for experiments or evaluation.

## Key Results / Accuracy
Write 2-3 bullet points with the actual results, metrics, accuracy numbers, or performance claims from the paper.

## Key Takeaways
Write 2-3 bullet points summarizing the most important lessons from the paper.

Formatting rules:
- Use ## for section headings.
- Use - for bullet points.
- Keep text concise. Each bullet point should be 1-2 sentences.
- Do not use tables, code blocks, or nested lists.
- Do not write long paragraphs.

Paper text:
{extracted_text[:12000]}
"""
