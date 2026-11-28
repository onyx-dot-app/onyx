# The description of the question tool that the model reads; each shape
# fills in its limits.

QUESTION_TOOL_DESCRIPTION = """Ask the user 1-{max_questions} short multiple-choice questions and wait for the answers.

Prefer reasonable assumptions: ask only when the answer materially changes the work and you cannot infer it from the conversation. Do not ask for permission to continue or to confirm a plan. Ask all your questions in one call.

Give each question 2-{max_options} options. Make the options exclusive, or let the user choose several when more than one option can apply. Put the recommended option first and end its label with "(Recommended)". Do not add an "Other" option: the user can always write their own answer.

The result holds the user's answers by {answer_keys}, or the text that the user typed instead. If the user does not answer, continue with your best judgment."""
