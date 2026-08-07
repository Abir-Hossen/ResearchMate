from .technical_prompt import build_technical_prompt as build_technical_prompt_text


def build_technical_prompt(extracted_text):
    return build_technical_prompt_text(extracted_text)
