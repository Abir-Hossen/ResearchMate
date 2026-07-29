from .base import build_feature_prompt


def build_quiz_prompt(extracted_text):
    instruction = (
        "Create quiz questions that assess understanding of the paper's key ideas."
    )
    return build_feature_prompt(extracted_text, 'quiz questions', instruction)
