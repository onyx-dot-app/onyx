"""Exercise pin PR publication against a real local Git remote."""

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).parent.resolve()
INSTALLER = "backend/onyx/server/features/build/sandbox/image/install-browser.sh"


def run(
    root: Path, *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args, cwd=root, env=env, capture_output=True, text=True, check=False
    )


class TaskPRTests(unittest.TestCase):
    def test_publisher_excludes_pre_staged_unapproved_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "repo"
            root.mkdir()
            remote = Path(directory) / "remote.git"
            run(root, "git", "init", "-b", "main")
            run(root, "git", "config", "user.name", "Test")
            run(root, "git", "config", "user.email", "test@example.com")
            (root / "approved.txt").write_text("before")
            (root / "delete.txt").write_text("remove me")
            (root / "unapproved.txt").write_text("before")
            run(root, "git", "add", ".")
            self.assertEqual(run(root, "git", "commit", "-m", "initial").returncode, 0)
            run(root, "git", "clone", "--bare", str(root), str(remote))
            run(root, "git", "remote", "add", "origin", str(remote))
            run(root, "git", "fetch", "origin")
            (root / "approved.txt").write_text("after")
            run(root, "git", "rm", "delete.txt")
            (root / "unapproved.txt").write_text("after")
            (root / "unapproved-new.txt").write_text("after")
            run(root, "git", "add", ".")
            binaries = Path(directory) / "bin"
            binaries.mkdir()
            gh = binaries / "gh"
            gh.write_text(
                '#!/bin/sh\nif [ "$1 $2" = "pr list" ] && [ -f "$CREATED" ]; then echo 123; fi\nif [ "$1 $2" = "pr create" ]; then touch "$CREATED"; fi\nexit 0\n'
            )
            gh.chmod(0o755)
            env = {
                **os.environ,
                "PATH": f"{binaries}:{os.environ['PATH']}",
                "FILES": "approved.txt delete.txt",
                "BASE": "main",
                "BRANCH": "auto/test",
                "PR_TITLE": "chore: update approved file",
                "TASK_NAME": "test",
                "RUN_URL": "https://example.com/run",
                "REPO_URL": "https://example.com/repo",
                "GITHUB_OUTPUT": str(Path(directory) / "output"),
                "CREATED": str(Path(directory) / "created"),
                "DIFF_VALIDATOR": "",
            }
            result = run(root, "bash", str(SCRIPTS / "publish-task-pr.sh"), env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            changed = run(
                root, "git", "diff", "--name-only", "origin/main", "HEAD"
            ).stdout.splitlines()
            self.assertEqual(changed, ["approved.txt", "delete.txt"])
            self.assertEqual((root / "unapproved.txt").read_text(), "after")
            self.assertEqual((root / "unapproved-new.txt").read_text(), "after")

            failed_sha = run(root, "git", "rev-parse", "HEAD").stdout.strip()
            run(root, "git", "push", "origin", "--delete", "auto/test")
            Path(env["CREATED"]).unlink()
            run(root, "git", "checkout", "main")
            (root / "approved.txt").write_text("repaired")
            result = run(
                root,
                "bash",
                str(SCRIPTS / "publish-task-pr.sh"),
                env={**env, "FAILED_SHA": failed_sha},
            )
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("Repair target changed", result.stderr)
            self.assertEqual(
                run(root, "git", "ls-remote", "origin", "refs/heads/auto/test").stdout,
                "",
            )


class BrowserUpdatePRTests(unittest.TestCase):
    def test_publish_retry_and_reject_extra_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "repo"
            root.mkdir()
            remote = Path(directory) / "remote.git"
            self.assertEqual(run(root, "git", "init", "-b", "main").returncode, 0)
            run(root, "git", "config", "user.name", "Test")
            run(root, "git", "config", "user.email", "test@example.com")
            target = root / INSTALLER
            target.parent.mkdir(parents=True)
            shutil.copyfile(SCRIPTS.parents[1] / INSTALLER, target)
            scripts = root / ".github/scripts"
            scripts.mkdir(parents=True)
            for name in (
                "publish-task-pr.sh",
                "update-sandbox-browser.sh",
                "chrome-stable-version.sh",
                "verify-browser-pin.py",
            ):
                shutil.copy2(SCRIPTS / name, scripts / name)
            reviewers = root / ".github/actions/slack-notify/cve-reviewers.json"
            reviewers.parent.mkdir(parents=True)
            reviewers.write_text(json.dumps(["reviewer"]))
            run(root, "git", "add", ".")
            self.assertEqual(run(root, "git", "commit", "-m", "initial").returncode, 0)
            self.assertEqual(
                run(root, "git", "clone", "--bare", str(root), str(remote)).returncode,
                0,
            )
            run(root, "git", "remote", "add", "origin", str(remote))
            run(root, "git", "fetch", "origin")
            # A version-only change cannot pass the required pin contract.
            original = target.read_text()
            target.write_text(
                re.sub(
                    r"^version=.*$", "version=999.0.1.2", original, flags=re.MULTILINE
                )
            )
            run(root, "git", "add", INSTALLER)
            run(root, "git", "commit", "-m", "incomplete pin")
            verification = run(
                root,
                "python3",
                ".github/scripts/verify-browser-pin.py",
                "origin/main",
                "HEAD",
            )
            self.assertNotEqual(verification.returncode, 0)
            self.assertIn("must change both checksums", verification.stderr)
            run(root, "git", "reset", "--hard", "origin/main")
            binaries = Path(directory) / "bin"
            binaries.mkdir()
            fixtures = {
                "curl": '#!/bin/sh\ncase "$*" in\n*last-known*) printf \'{"channels":{"Stable":{"version":"%s"}}}\' "$STABLE";;\n*linux-arm64*) printf "%s-arm64" "$STABLE";;\n*) printf "%s-amd64" "$STABLE";;\nesac\n',
                "gh": """#!/bin/sh
case "$1 $2" in
"pr list") if [ -n "$EXISTING_PR" ] || [ -f "$CREATED_PR" ]; then echo 123; fi;;
"pr create") touch "$CREATED_PR"; echo "pr create" >> "$PR_CALLS";;
"pr view")
  if [ -f "$REVIEW_DONE" ]; then
    echo '{"reviewRequests":[{"login":"reviewer"}],"reviews":[]}'
  else
    echo '{"reviewRequests":[],"reviews":[]}'
  fi;;
"pr edit")
  if [ "${FAIL_EDIT:-}" = true ]; then exit 1; fi
  case "$*" in *--add-reviewer*) touch "$REVIEW_DONE";; esac
  echo "$*" >> "$PR_CALLS";;
esac
""",
                "shuf": "#!/bin/sh\nhead -1\n",
            }
            for name, content in fixtures.items():
                (binaries / name).write_text(content)
                (binaries / name).chmod(0o755)
            env = {
                **os.environ,
                "PATH": f"{binaries}:{os.environ['PATH']}",
                "GITHUB_OUTPUT": str(Path(directory) / "output"),
                "RUN_URL": "https://example.com/run",
                "PR_CALLS": str(Path(directory) / "calls"),
                "EXISTING_PR": "",
                "STABLE": "999.0.1.2",
                "CREATED_PR": str(Path(directory) / "created"),
                "REVIEW_DONE": str(Path(directory) / "reviewed"),
                "REVIEWER": "reviewer",
                "BASE": "main",
                "BRANCH": "auto/sandbox-browser/main",
                "FILES": INSTALLER,
                "DIFF_VALIDATOR": ".github/scripts/verify-browser-pin.py",
                "PR_TITLE": "chore(deps): update browser",
                "TASK_NAME": "test",
                "REPO_URL": "https://github.com/onyx-dot-app/onyx",
            }
            args = ("bash", ".github/scripts/publish-task-pr.sh")

            def publish(
                environment: dict[str, str],
            ) -> subprocess.CompletedProcess[str]:
                run(root, "git", "checkout", "main")
                update = run(
                    root,
                    "bash",
                    ".github/scripts/update-sandbox-browser.sh",
                    INSTALLER,
                    env=environment,
                )
                self.assertEqual(update.returncode, 0, update.stderr)
                return run(root, *args, env=environment)

            result = publish({**env, "FAIL_EDIT": "true"})
            self.assertNotEqual(result.returncode, 0)
            branch = "auto/sandbox-browser/main"
            first = run(
                root, "git", "ls-remote", "origin", f"refs/heads/{branch}"
            ).stdout
            self.assertIn("pr create", Path(env["PR_CALLS"]).read_text())
            result = publish({**env, "EXISTING_PR": "123"})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("PR #123 already has this output.", result.stdout)
            self.assertTrue(Path(env["REVIEW_DONE"]).exists())
            output = Path(env["GITHUB_OUTPUT"])
            self.assertIn("pr_number=123", output.read_text())
            self.assertIn("notify=true", output.read_text())
            output.unlink()
            calls_before = Path(env["PR_CALLS"]).read_text().count("--add-reviewer")
            result = publish(env)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("notify=false", output.read_text())
            self.assertIn("pr_number=123", output.read_text())
            self.assertEqual(
                Path(env["PR_CALLS"]).read_text().count("--add-reviewer"), calls_before
            )
            self.assertEqual(
                first,
                run(root, "git", "ls-remote", "origin", f"refs/heads/{branch}").stdout,
            )
            # Identical output must refresh a PR if the base changed its paths.
            run(root, "git", "checkout", "main")
            intermediate = run(
                root,
                "bash",
                ".github/scripts/update-sandbox-browser.sh",
                INSTALLER,
                env={**env, "STABLE": "998.0.1.2"},
            )
            self.assertEqual(intermediate.returncode, 0, intermediate.stderr)
            run(root, "git", "add", INSTALLER)
            run(root, "git", "commit", "-m", "intermediate base pin")
            run(root, "git", "push", "origin", "main")
            result = publish(env)
            self.assertEqual(result.returncode, 0, result.stderr)
            current = run(
                root, "git", "ls-remote", "origin", f"refs/heads/{branch}"
            ).stdout
            self.assertNotEqual(first, current)
            self.assertEqual(
                run(root, "git", "merge-base", "HEAD", "origin/main").stdout,
                run(root, "git", "rev-parse", "origin/main").stdout,
            )
            self.assertEqual(
                run(
                    root, "git", "merge-tree", "--write-tree", "HEAD", "origin/main"
                ).returncode,
                0,
            )
            env = {**env, "EXISTING_PR": "123", "STABLE": "1000.0.1.2"}
            result = publish(env)
            self.assertEqual(result.returncode, 0, result.stderr)
            refreshed = run(
                root, "git", "ls-remote", "origin", f"refs/heads/{branch}"
            ).stdout
            self.assertNotEqual(first, refreshed)
            calls = Path(env["PR_CALLS"]).read_text()
            self.assertEqual(calls.count("pr create"), 1)
            self.assertIn("pr edit 123", calls)

            # Move the real remote after the publisher captures its lease.
            race = run(
                root,
                "git",
                "commit-tree",
                "HEAD^{tree}",
                "-p",
                "HEAD",
                "-m",
                "Concurrent writer",
            )
            self.assertEqual(race.returncode, 0, race.stderr)
            race_sha = race.stdout.strip()
            transfer = run(
                root,
                "git",
                "push",
                "origin",
                f"{race_sha}:refs/heads/concurrent-writer",
            )
            self.assertEqual(transfer.returncode, 0, transfer.stderr)
            hook = root / ".git/hooks/post-commit"
            hook.write_text(
                '#!/bin/sh\ngit --git-dir="$RACE_REMOTE" update-ref "$RACE_REF" "$RACE_SHA"\n'
            )
            hook.chmod(0o755)
            env = {
                **env,
                "STABLE": "1001.0.1.2",
                "RACE_REMOTE": str(remote),
                "RACE_REF": f"refs/heads/{branch}",
                "RACE_SHA": race_sha,
            }
            result = publish(env)
            hook.unlink()
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("stale info", result.stderr)
            self.assertEqual(
                run(
                    root, "git", "ls-remote", "origin", f"refs/heads/{branch}"
                ).stdout.split()[0],
                race_sha,
            )
            run(root, "git", "fetch", "origin")

            # Refuse to overwrite or auto-merge unrelated changes in an existing PR.
            run(root, "git", "checkout", "-b", "tamper", f"origin/{branch}")
            (root / "unexpected.txt").write_text("unexpected change")
            run(root, "git", "add", "unexpected.txt")
            run(root, "git", "commit", "-m", "unrelated")
            run(root, "git", "push", "origin", f"HEAD:refs/heads/{branch}")
            run(root, "git", "checkout", "main")
            result = publish({**env, "EXISTING_PR": "123"})
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("must change only install-browser.sh", result.stderr)


if __name__ == "__main__":
    unittest.main()
