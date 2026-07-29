from .prompts import (
    build_beginner_prompt,
    build_difficulty_prompt,
    build_flashcards_prompt,
    build_glossary_prompt,
    build_quiz_prompt,
    build_section_learning_prompt,
    build_technical_prompt,
    build_viva_prompt,
)


def get_beginner_prompt(extracted_text):
    return build_beginner_prompt(extracted_text)


def get_technical_prompt(extracted_text):
    return build_technical_prompt(extracted_text)


def get_glossary_prompt(extracted_text):
    return build_glossary_prompt(extracted_text)


def get_section_learning_prompt(extracted_text):
    return build_section_learning_prompt(extracted_text)


def get_flashcards_prompt(extracted_text):
    return build_flashcards_prompt(extracted_text)


def get_viva_prompt(extracted_text):
    return build_viva_prompt(extracted_text)


def get_quiz_prompt(extracted_text):
    return build_quiz_prompt(extracted_text)


def get_difficulty_prompt(extracted_text):
    return build_difficulty_prompt(extracted_text)
