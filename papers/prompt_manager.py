from .prompts import (
    build_beginner_prompt,
    build_difficulty_prompt,
    build_flashcards_prompt,
    build_glossary_prompt,
    build_quiz_prompt,
    build_revision_notes_prompt,
    build_section_learning_prompt,
    build_technical_prompt,
    build_viva_prompt,
    get_section_detection_prompt as build_section_detection_prompt,
    get_single_section_explanation_prompt as build_single_section_explanation_prompt,
)


def get_beginner_prompt(extracted_text):
    return build_beginner_prompt(extracted_text)


def get_technical_prompt(extracted_text):
    return build_technical_prompt(extracted_text)


def get_glossary_prompt(extracted_text):
    return build_glossary_prompt(extracted_text)


def get_section_learning_prompt(extracted_text):
    return build_section_learning_prompt(extracted_text)


def get_section_detection_prompt(extracted_text):
    return build_section_detection_prompt(extracted_text)


def get_single_section_explanation_prompt(section_title, section_text):
    return build_single_section_explanation_prompt(section_title, section_text)


def get_flashcards_prompt(extracted_text):
    return build_flashcards_prompt(extracted_text)


def get_viva_prompt(extracted_text):
    return build_viva_prompt(extracted_text)


def get_quiz_prompt(extracted_text):
    return build_quiz_prompt(extracted_text)


def get_revision_notes_prompt(extracted_text):
    return build_revision_notes_prompt(extracted_text)


def get_difficulty_prompt(extracted_text):
    return build_difficulty_prompt(extracted_text)
