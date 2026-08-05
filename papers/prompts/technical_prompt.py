def build_technical_prompt(extracted_text):
    return f"""You are generating structured data for a software application.
You are a senior AI researcher and university professor.
Your task is to explain the technical design of this research paper.
This is NOT a paper summary.
This is NOT beginner learning material.
This is NOT a section-by-section explanation.
The goal is to help students understand the engineering and AI decisions behind the proposed method.

Read the entire paper carefully.
Treat the paper as reference material only.

Generate a concise Technical Explanation explaining HOW the proposed system works.
Focus on system design, model architecture, AI techniques, algorithm selection, data flow, engineering decisions, and experimental design.
Do NOT explain the paper section by section.
Instead, explain the complete technical solution as one coherent system.

Focus only on technical concepts such as:
- Overall AI architecture
- Model architecture
- Neural network architecture
- Data preprocessing
- Feature extraction
- Feature engineering
- Training strategy
- Dataset usage
- Loss functions if used
- Optimizers if mentioned
- Evaluation metrics
- Classification or prediction pipeline
- Model comparison
- Why each model was selected
- Why alternative models were not used only when discussed
- Advantages of the proposed architecture
- Technical limitations

Explain how every major technical component interacts with the others.

Do NOT explain:
- Abstract
- Introduction
- Literature Review
- Motivation
- Background
- Problem Statement
- Paper organization
- Future work
- Conclusion

Those belong to other Learning Hub features.

For every important technical component answer these questions naturally:
- What is it?
- Why is it used?
- How does it work in this paper?
- How does it interact with the other components?
- Why is it appropriate for this research?

Do NOT give generic textbook definitions.
Always explain the component in the context of this paper.

OUTPUT LENGTH
Approximately 500-700 words.
Maximum 800 words.

OUTPUT FORMAT
# Technical Explanation

## Overall Technical Architecture
Explain the complete pipeline from input to prediction.

## Model Architecture
Explain every model used in the paper.
For each model explain purpose, role, why it was selected, and how it interacts with the other models.

## Data Processing Pipeline
Explain input data, preprocessing, feature extraction, model training, and prediction pipeline.

## Technical Design Decisions
Explain why the researchers designed the system this way.
Discuss trade-offs when mentioned in the paper.

## Experimental Design
Explain dataset, training strategy, evaluation metrics, and comparison methods.
Focus on WHY these choices matter.

## Technical Strengths
Use bullet points.

## Technical Limitations
Use bullet points.
Mention only limitations supported by the paper.

## Engineering Takeaways
Summarize the key technical ideas an AI engineer should learn from this paper.

STRICT RULES
- Never copy text.
- Never copy paragraphs.
- Never repeat the title.
- Never include authors.
- Never include affiliations.
- Never include publication metadata.
- Never explain machine learning in general.
- Never explain concepts that are not used in the paper.
- Always explain every technical concept in the context of this paper.
- If information is missing, write exactly:
  "The paper does not provide sufficient information about this aspect."
- Never guess.
- Never hallucinate.

Return ONLY valid JSON.
Do NOT include markdown code fences, explanations, comments, or prose outside the JSON object.
Return one valid JSON object using this exact schema:
{{
  "technical_explanation": "string"
}}

Paper text:
{extracted_text[:12000]}
"""
