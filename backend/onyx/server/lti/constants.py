"""Shared constants for the LTI / Virtual Tutor flow."""

# Personas tagged with this label are treated as Virtual Tutors and become
# eligible for matching against a Canvas course on LTI launch. The frontend
# (web/src/refresh-pages/admin/TutorPage/constants.ts) keeps a parallel
# constant — keep them in sync.
VIRTUAL_TUTOR_LABEL = "Virtual Tutor"
