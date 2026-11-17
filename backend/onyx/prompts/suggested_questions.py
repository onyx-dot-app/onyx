# Triage questions, asked once per numbered excerpt in a decision request.

SQ_TRIAGE_USABLE_QUESTION = (
    "How good is excerpt [{index}] as the source of a question a colleague "
    "would ask an AI assistant at work, answered by this excerpt alone?"
)

# Score levels, worst first. The index of a level is its score.
SQ_TRIAGE_USABLE_LEVELS = [
    (
        "useless",
        "navigation, boilerplate, legal text, a fragment, or nothing to ask about",
    ),
    ("weak", "on a work topic, but vague or hard to ask about"),
    ("good", "one clear fact, rule or process a colleague could ask about"),
    (
        "excellent",
        "a specific number, date, name, rule or list that people at work need",
    ),
]

SQ_TRIAGE_SENSITIVE_QUESTION = (
    "Does excerpt [{index}] reveal private information: pay, health, "
    "performance reviews, credentials, or personal details about a named person?"
)

SQ_TRIAGE_TOPIC_QUESTION = "Which kind of work is excerpt [{index}] most useful for?"

# Values match UseCase.
SQ_TRIAGE_TOPIC_CHOICES = [
    ("hr", "people, policies, benefits, time off, hiring"),
    ("engineering", "systems, code, infrastructure, how things are built"),
    ("support", "customer problems, troubleshooting, how issues were handled"),
    ("sales", "customers, deals, pricing, what was promised to customers"),
    ("other", "anything else"),
]

SQ_TRIAGE_FACT_QUESTION = (
    "Does excerpt [{index}] state a concrete fact: a number, a date, a name or "
    "a short list?"
)
