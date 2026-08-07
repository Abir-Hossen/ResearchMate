from .base import build_feature_prompt


def build_quiz_prompt(extracted_text):
    instruction = (
        "Create exactly 10 paper-specific quiz questions that assess understanding of the paper's key ideas. "
        "The questions must be grounded in the uploaded paper and should test conceptual understanding, not generic textbook knowledge. "
        "Generate 4 easy, 4 medium, and 2 hard questions. "
        "Each question must include four realistic options, one correct answer, and a concise explanation of why the correct answer is right. "
        "Return the questions as a JSON array of objects in the schema described below, with each item containing question, options, correct_answer, difficulty, and explanation."
    )
    return build_feature_prompt(extracted_text, 'quiz questions', instruction)
