from .base import build_feature_prompt


def build_flashcards_prompt(extracted_text):
    instruction = (
        "Create concise flashcards that capture the key concepts of the paper. "
        "Each flashcard should contain a question and a short answer."
    )
    return build_feature_prompt(extracted_text, 'flashcards', instruction)
