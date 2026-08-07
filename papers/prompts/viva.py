from .base import build_feature_prompt


def build_viva_prompt(extracted_text):
    instruction = (
        "Create 12-15 paper-specific viva preparation questions for a university thesis defense. "
        "Generate questions only from the uploaded paper and never invent methods, datasets, or models that are not present in the paper. "
        "Do not generate multiple-choice questions or glossary-style definitions. "
        "Group them into three categories: Basic Understanding, Technical Understanding, and Critical Thinking. "
        "For each question include a concise answer (100-180 words), a difficulty level (Easy, Medium, or Hard), a category, and an examiner tip."
    )
    return build_feature_prompt(extracted_text, 'viva preparation questions', instruction)
