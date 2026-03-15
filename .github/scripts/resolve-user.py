#!/usr/bin/env python3
"""Resolve users between GitHub and Slack using the shared mapping file.

Usage:
    resolve-user.py --github-to-slack <github_username>
    resolve-user.py --slack-to-github <slack_id>
    resolve-user.py --allowed-mergers
"""

import argparse
import sys
from pathlib import Path

import yaml


def load_users() -> dict[str, str]:
    users_file = (
        Path(__file__).resolve().parent.parent / "data" / "slack-github-users.yaml"
    )
    with open(users_file) as f:
        return yaml.safe_load(f)["user_mappings"]


def github_to_slack(gh_user: str) -> str | None:
    users = load_users()
    gh_lower = gh_user.lower()
    for slack_id, github in users.items():
        if github.lower() == gh_lower:
            return slack_id
    return None


def slack_to_github(slack_id: str) -> str | None:
    users = load_users()
    return users.get(slack_id)


def allowed_mergers() -> list[str]:
    return list(load_users().values())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--github-to-slack", metavar="USERNAME")
    group.add_argument("--slack-to-github", metavar="SLACK_ID")
    group.add_argument("--allowed-mergers", action="store_true")
    args = parser.parse_args()

    if args.github_to_slack:
        result = github_to_slack(args.github_to_slack)
        if result is None:
            sys.exit(1)
        print(result)
    elif args.slack_to_github:
        result = slack_to_github(args.slack_to_github)
        if result is None:
            sys.exit(1)
        print(result)
    elif args.allowed_mergers:
        for username in allowed_mergers():
            print(username)


if __name__ == "__main__":
    main()
