from .base import build_feature_prompt


def build_technical_prompt(extracted_text):
    instruction = (
        "Write a technical explanation of the paper's core methods and contributions. "
        "Focus on substance and precision."
    )
    return build_feature_prompt(extracted_text, 'a technical explanation', instruction)
