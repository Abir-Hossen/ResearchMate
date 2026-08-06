def build_glossary_prompt(extracted_text):
    return f"""You are a university teaching assistant helping undergraduate students understand the technical terminology used in this research paper.

Read the paper carefully and identify the technical terms that are actually important for understanding this specific paper.

Requirements:
- Extract 15–20 glossary entries.
- Choose terms that are meaningfully relevant to this paper, not generic words.
- Base every term on the paper content itself. Do not reuse a placeholder example such as CNN unless the paper genuinely discusses it.
- Prefer terms such as algorithms, models, architectures, datasets, metrics, mathematical concepts, frameworks, training methods, evaluation concepts, abbreviations, or domain-specific terminology.
- Ignore common English words and broad vocabulary that is not central to the paper.
- Keep each explanation short, precise, and useful for a student reading this paper.
- Keep each explanation to about 1 short paragraph.
- Keep the role-in-paper section to 1–2 short sentences.
- If the paper does not clearly explain the term's role, write: "The paper does not explicitly describe how this concept is used."
- Do not write long introductions or repetitive explanations.

Return Markdown using exactly this structure:

# AI Glossary

## Term Name

### Explanation
Write a concise explanation in simple language. Keep it short and specific to the paper.

### Role in This Paper
Write a short, paper-specific description of how the term is used in this paper. If uncertain, use the required fallback sentence.

---

Repeat this structure for every glossary term.

Paper text:
{extracted_text[:12000]}
"""
