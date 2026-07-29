from .base import build_feature_prompt


def build_viva_prompt(extracted_text):
    instruction = (
        "Create viva-style questions and suggested answers that a student could use to discuss the paper."
    )
    return build_feature_prompt(extracted_text, 'viva preparation questions', instruction)
