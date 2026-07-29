from .base import build_feature_prompt


def build_beginner_prompt(extracted_text):
    instruction = (
        "Write a beginner-friendly explanation of the paper's main idea. "
        "Keep it clear, simple, and easy to understand."
    )
    return build_feature_prompt(extracted_text, 'a beginner explanation', instruction)
