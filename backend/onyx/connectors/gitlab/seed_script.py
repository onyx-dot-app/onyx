#!/usr/bin/env python3
"""
Script to programmatically create merge requests and issues in a GitLab project using the python-gitlab library.

Usage:
  1. Install dependencies: pip install python-gitlab faker
  2. Set environment variables:
       - GITLAB_URL: URL of your GitLab instance (default: https://gitlab.com)
       - GITLAB_TOKEN: Your personal access token with API scope
       - GITLAB_PROJECT_ID: The ID or path ("namespace/project") of the target project
  3. Update the `merge_requests` and `issues` lists below with your desired definitions.
  4. Run: python create_gitlab_mrs_issues.py
"""
import argparse
import os
import random
import sys
from typing import NotRequired
from typing import TypedDict

import gitlab
from faker import Faker
from gitlab.v4.objects import Project

fake = Faker()

# Configuration from environment
GITLAB_URL: str = os.getenv("GITLAB_URL", "https://gitlab.com")
GITLAB_TOKEN: str | None = os.getenv("GITLAB_TOKEN")
GITLAB_PROJECT_ID: str | None = os.getenv(
    "GITLAB_PROJECT_ID"
)  # e.g. "my-group/my-project" or numeric ID


class MergeRequest(TypedDict):
    source_branch: str
    target_branch: NotRequired[str]
    title: str
    description: NotRequired[str]
    assignee_ids: NotRequired[list[int] | None]
    labels: NotRequired[list[str] | None]


class Issue(TypedDict):
    title: str
    description: NotRequired[str]
    assignee_ids: NotRequired[list[int] | None]
    labels: NotRequired[list[str] | None]
    milestone_id: NotRequired[int]


def generate_branch_name() -> str:
    """Generate a random branch name following common conventions."""
    branch_types = ["feature", "bugfix", "hotfix", "refactor", "docs"]
    branch_type = random.choice(branch_types)
    words = fake.words(nb=2)
    return f"{branch_type}/{'-'.join(words)}"


def generate_mr_title() -> str:
    """Generate a random merge request title."""
    actions = ["Add", "Implement", "Update", "Fix", "Refactor", "Improve", "Remove"]
    components = [
        "feature",
        "component",
        "module",
        "system",
        "API",
        "UI",
        "backend",
        "frontend",
    ]
    return f"{random.choice(actions)} {random.choice(components)} {fake.word()}"


def generate_mr_description() -> str:
    """Generate a random merge request description."""
    return fake.paragraph(nb_sentences=3)


def generate_random_mr() -> MergeRequest:
    """Generate a random merge request."""
    return {
        "source_branch": generate_branch_name(),
        "target_branch": "main",
        "title": generate_mr_title(),
        "description": generate_mr_description(),
        "assignee_ids": (
            random.sample(range(1, 100), random.randint(0, 2))
            if random.random() < 0.3
            else None
        ),
        "labels": (
            random.sample(
                [
                    "feature",
                    "bug",
                    "enhancement",
                    "documentation",
                    "backend",
                    "frontend",
                ],
                random.randint(0, 3),
            )
            if random.random() < 0.4
            else None
        ),
    }


# Define your merge requests here
merge_requests_manual: list[MergeRequest] = [
    # Example of a manually defined MR
    {
        "source_branch": "feature/awesome-feature",
        "target_branch": "main",
        "title": "Add awesome feature",
        "description": "This MR implements the awesome feature",
    },
    # Add more MRs as needed
]

# Define your issues here
issues_manual: list[Issue] = [
    {
        "title": "Investigate performance issue",
        "description": "Investigate and resolve the performance degradation on endpoint X",
        # 'assignee_ids': [123],
        # 'labels': ['bug', 'high priority'],
        # 'milestone_id': 1,
    },
    # Add more issues as needed
]


# +++ Add issue generation functions +++
def generate_issue_title() -> str:
    """Generate a random issue title."""
    actions = ["Investigate", "Fix", "Implement", "Discuss", "Improve", "Resolve"]
    areas = [
        "performance",
        "bug",
        "feature request",
        "UI glitch",
        "API stability",
        "documentation",
    ]
    return f"{random.choice(actions)} {random.choice(areas)} in {fake.word()}"


def generate_issue_description() -> str:
    """Generate a random issue description."""
    return fake.paragraph(nb_sentences=random.randint(2, 5))


def generate_random_issue() -> Issue:
    """Generate a random issue."""
    return {
        "title": generate_issue_title(),
        "description": generate_issue_description(),
        "assignee_ids": (
            random.sample(
                range(1, 100), random.randint(0, 2)
            )  # Assuming user IDs up to 100
            if random.random() < 0.2
            else None
        ),
        "labels": (
            random.sample(
                [
                    "bug",
                    "feature",
                    "enhancement",
                    "question",
                    "help wanted",
                    "good first issue",
                    "performance",
                    "security",
                ],
                random.randint(0, 3),
            )
            if random.random() < 0.5
            else None
        ),
        # 'milestone_id': None # Add logic if milestones are relevant
    }


# +++ End added issue generation functions +++


def create_merge_requests(project: Project, mrs: list[MergeRequest]) -> None:
    for mr in mrs:
        payload = {
            "source_branch": mr["source_branch"],
            "target_branch": mr.get("target_branch", "main"),
            "title": mr["title"],
            "description": mr.get("description", ""),
        }
        assignee_ids = mr.get("assignee_ids")
        if assignee_ids is not None:
            payload["assignee_ids"] = ",".join(str(id) for id in assignee_ids)
        labels = mr.get("labels")
        if labels is not None:
            payload["labels"] = ",".join(labels)
        try:
            created = project.mergerequests.create(payload)
            print(f"Created MR !{created.iid}: {created.title}")
        except Exception as e:
            print(f"Failed to create MR '{mr['title']}': {e}")


def create_issues(project: Project, issues_list: list[Issue]) -> None:
    for issue in issues_list:
        payload = {
            "title": issue["title"],
            "description": issue.get("description", ""),
        }
        assignee_ids = issue.get("assignee_ids")
        if assignee_ids is not None:
            payload["assignee_ids"] = ",".join(str(id) for id in assignee_ids)
        labels = issue.get("labels")
        if labels is not None:
            payload["labels"] = ",".join(labels)
        milestone_id = issue.get("milestone_id")
        if milestone_id is not None:
            payload["milestone_id"] = str(milestone_id)
        try:
            created = project.issues.create(payload)
            print(f"Created Issue #{created.iid}: {created.title}")
        except Exception as e:
            print(f"Failed to create issue '{issue['title']}': {e}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate GitLab Merge Requests and Issues."
    )
    parser.add_argument(
        "--num-mrs",
        type=int,
        default=50,
        help="Number of random merge requests to generate.",
    )
    parser.add_argument(
        "--num-issues",
        type=int,
        default=20,
        help="Number of random issues to generate.",
    )
    args = parser.parse_args()

    if not GITLAB_TOKEN:
        print("Error: GITLAB_TOKEN environment variable is not set.")
        sys.exit(1)
    if not GITLAB_PROJECT_ID:
        print("Error: GITLAB_PROJECT_ID environment variable is not set.")
        sys.exit(1)

    # Authenticate with GitLab
    gl = gitlab.Gitlab(GITLAB_URL, private_token=GITLAB_TOKEN)
    try:
        project = gl.projects.get(GITLAB_PROJECT_ID)
    except Exception as e:
        print(f"Error accessing project '{GITLAB_PROJECT_ID}': {e}")
        sys.exit(1)

    # Prepare MRs list (manual + random)
    all_merge_requests = list(merge_requests_manual)  # Start with manual ones
    print(f"Generating {args.num_mrs} random merge requests...")
    for _ in range(args.num_mrs):
        all_merge_requests.append(generate_random_mr())

    # Prepare Issues list (manual + random)
    all_issues = list(issues_manual)  # Start with manual ones
    print(f"Generating {args.num_issues} random issues...")
    for _ in range(args.num_issues):
        all_issues.append(generate_random_issue())

    # Create MRs and issues
    print(f"Creating {len(all_merge_requests)} total merge requests...")
    create_merge_requests(project, all_merge_requests)
    print(f"Creating {len(all_issues)} total issues...")
    create_issues(project, all_issues)


if __name__ == "__main__":
    main()
