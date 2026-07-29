from .base import build_feature_prompt


def build_section_learning_prompt(extracted_text):
    instruction = (
        "Summarize the paper by section and explain what a learner should focus on in each section."
    )
    return build_feature_prompt(extracted_text, 'section-based learning guidance', instruction)
