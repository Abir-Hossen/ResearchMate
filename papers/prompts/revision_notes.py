def build_revision_notes_prompt(extracted_text):
    return f"""You are generating concise revision notes for a student studying a research paper.

Instructions:
- Write the response in Markdown.
- Focus on the most important concepts, methods, findings, and takeaways from the paper.
- Keep the tone concise and exam-friendly.
- Do not invent facts or add information not supported by the paper.
- Do not repeat the full paper text.
- Structure the notes with a short title, key points, and a final summary.

Paper text:
{extracted_text[:12000]}
"""
