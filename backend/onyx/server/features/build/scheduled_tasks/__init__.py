"""Scheduled Tasks feature for Onyx Craft.

Internals split across:
- schedule.py:      pure cron/timezone helpers (croniter + cron-descriptor).
- sandbox_lease.py: Redis-lock wrapper keyed on sandbox_id; serializes
                    interactive and scheduled prompts within one pod.
- executor.py:      headless agent runner (added by the background-workers
                    layer in a later phase).
- api.py:           FastAPI router (added by the APIs layer).
"""
