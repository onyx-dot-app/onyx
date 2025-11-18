import os

EXPLORATION_TEST_USE_DC_DEFAULT = (
    os.environ.get("EXPLORATION_TEST_USE_DC_DEFAULT") or "false"
).lower() == "true"
EXPLORATION_TEST_USE_CALRIFIER_DEFAULT = (
    os.environ.get("EXPLORATION_TEST_USE_CALRIFIER_DEFAULT") or "false"
).lower() == "true"
EXPLORATION_TEST_USE_PLAN_DEFAULT = (
    os.environ.get("EXPLORATION_TEST_USE_PLAN_DEFAULT") or "false"
).lower() == "true"
EXPLORATION_TEST_USE_PLAN_UPDATES_DEFAULT = (
    os.environ.get("EXPLORATION_TEST_USE_PLAN_UPDATES_DEFAULT") or "false"
).lower() == "true"
EXPLORATION_TEST_USE_CORPUS_HISTORY_DEFAULT = (
    os.environ.get("EXPLORATION_TEST_USE_CORPUS_HISTORY_DEFAULT") or "false"
).lower() == "true"
EXPLORATION_TEST_USE_THINKING_DEFAULT = (
    os.environ.get("EXPLORATION_TEST_USE_THINKING_DEFAULT") or "false"
).lower() == "true"
