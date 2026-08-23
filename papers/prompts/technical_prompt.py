import re


def _extract_relevant_technical_context(extracted_text, max_chars=5500):
    if not extracted_text:
        return ''

    text = extracted_text.strip()
    blocks = [block.strip() for block in re.split(r'\n\s*\n+', text) if block.strip()]
    if not blocks:
        return text[:max_chars]

    priority_keywords = (
        'abstract', 'introduction', 'motivation', 'problem', 'method', 'approach',
        'model', 'architecture', 'dataset', 'experiment', 'evaluation', 'results',
        'findings', 'conclusion', 'limitation'
    )

    priority_blocks = []
    secondary_blocks = []
    for block in blocks:
        lowered = block.lower()
        if any(keyword in lowered for keyword in priority_keywords):
            priority_blocks.append(block)
        else:
            secondary_blocks.append(block)

    selected = []
    for block in priority_blocks + secondary_blocks:
        if len(' '.join(selected)) + len(block) + 1 <= max_chars:
            selected.append(block)
        else:
            break

    if not selected:
        return text[:max_chars]

    context = ' '.join(selected)
    context = re.sub(r'\s+', ' ', context).strip()
    if len(context) > max_chars:
        context = context[:max_chars].rsplit(' ', 1)[0]
    return context


def build_technical_prompt(extracted_text):
    context = _extract_relevant_technical_context(extracted_text)
    return f"""You are generating structured data for a software application.
You are a senior AI researcher and university professor.
Your task is to explain the technical design of this paper using only the provided paper context.

This explanation must be derived from the provided paper context. Do not provide a generic textbook explanation. If a technical detail is not present in the context, do not invent it.

Return ONLY valid JSON.
Do NOT include markdown code fences, explanations, comments, or prose outside the JSON object.
Return one valid JSON object using this exact schema:
{{
  "technical_explanation": "string"
}}

Explain the technical solution as a coherent paper-specific system, not as a generic summary.
Use this structure in order:

## Overall Technical Architecture
Explain the complete pipeline from input to prediction.

## Model Architecture
Explain the model or method used in the paper, how it works, and why it was chosen.

## Data Processing Pipeline
Explain the data or experimental setup, preprocessing, and training or evaluation flow.

## Technical Design Decisions
Explain the key design trade-offs described in the paper.

## Experimental Design
Explain dataset, evaluation, and reported results using the actual paper context.

## Technical Strengths
Use short bullet points.

## Technical Limitations
Use short bullet points, only if supported by the paper.

## Engineering Takeaways
Summarize the key technical lesson from the paper.

Instructions:
- Use only information supported by the provided paper context.
- Mention the actual method, model, dataset, experiment, or findings when they are present.
- Do not invent architectures, metrics, models, datasets, or results.
- Avoid generic background and introductory filler.
- Keep the explanation concise and clear.
- Target roughly 500-700 words.
- Treat the paper as reference material only.
- Never copy text.
- Never repeat the title.
- Do not generate additional fields or arrays.

Paper text:
{context}
"""
