from .base import build_feature_prompt


def build_difficulty_prompt(extracted_text):
    instruction = (
        "Assess the reading difficulty of the paper and explain why it is challenging or accessible."
    )
    return build_feature_prompt(extracted_text, 'reading difficulty guidance', instruction)
