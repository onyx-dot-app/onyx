# Historical review audit

Run from the repository root with Python 3 and authenticated GitHub CLI access.

```sh
python3 tools/review-eval/evaluate.py discover --ref origin/main \
  --since 2026-08-19T00:00:00Z --until 2026-11-17T23:59:59Z > /tmp/review-candidates.json
python3 tools/review-eval/evaluate.py collect 17043 17064 > /tmp/review-evidence.json
python3 tools/review-eval/evaluate.py score
```

Pin the ref to repeat a scan after main moves. Discovery uses first-parent
commit messages with squash PR numbers. The output contains leads, including
incidental links. Use GitHub PR bodies and commit messages to check leads and
look for links absent from the squash message. Compare the introducing and
fixing patches before writing the answer key. Record exclusions with reasons.

Collect each introducing PR and each control. Review the existing review
bodies, inline comments, replies, and discussion. Check the comment timestamp
against merge and the commit SHA against the reviewed patch. Count one match
per reviewer per bug. Use the earliest matching comment as evidence.
Treat a reviewer as covered if it left evidence of a completed review.

For a match, record whether the author fixed, declined, ignored, or merged
without fixing the issue. Use `unknown` if the evidence is insufficient.
Check the merged code even if GitHub marks a thread resolved.
For controls, count individual inline findings once, excluding replies and
duplicate summaries. Verify disposition in the author's reply or merged code.
Select controls from the same merge period and search for known follow-up fixes.

Copy `pilot.json` to update the labels. Use `--labels PATH` before `score`
to score the new file. Report overall recall and recall among covered cases.
Use matched cases as the denominator for the lost rate. A zero denominator
means the rate is undefined. The script reads GitHub and writes to stdout.
