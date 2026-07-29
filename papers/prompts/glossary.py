from .base import build_feature_prompt


def build_glossary_prompt(extracted_text):
    instruction = (
        "Extract the most important domain terms from the paper and provide a short glossary entry for each. "
        "Include a simple explanation and a technical explanation."
    )
    return build_feature_prompt(extracted_text, 'a glossary', instruction)
