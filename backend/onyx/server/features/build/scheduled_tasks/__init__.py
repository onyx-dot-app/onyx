"""Scheduled Tasks feature for Onyx Craft.

Internals split across:
- schedule.py:      pure cron/timezone helpers (croniter + cron-descriptor).
- executor.py:      headless agent runner (added by the background-workers
                    layer in a later phase).
- api.py:           FastAPI router (added by the APIs layer).
"""
