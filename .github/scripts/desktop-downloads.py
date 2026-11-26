"""Print desktop app download counts from GitHub release assets as Markdown.

Reads every release of the repository (GITHUB_REPOSITORY; GH_TOKEN for gh) and
sums the download_count of the desktop assets per platform and format.
"""

import json
import os
import subprocess
import sys
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from typing import TypedDict

# (asset name suffix, platform, format), first match wins.
KINDS: Sequence[tuple[str, str, str]] = (
    (".app.tar.gz.sig", "", ""),
    (".sig", "", ""),
    (".dmg", "macOS", "DMG"),
    (".app.tar.gz", "macOS", "Update archive"),
    ("arm64.exe", "Windows", "EXE arm64"),
    ("arm64-setup.exe", "Windows", "EXE arm64"),
    (".exe", "Windows", "EXE x64"),
    (".msi", "Windows", "MSI"),
    ("arm64.deb", "Linux", "DEB arm64"),
    (".deb", "Linux", "DEB x64"),
    ("aarch64.rpm", "Linux", "RPM arm64"),
    (".rpm", "Linux", "RPM x64"),
    (".AppImage", "Linux", "AppImage"),
)
PLATFORMS = ("macOS", "Windows", "Linux")
FEED = "latest.json"


class Asset(TypedDict):
    name: str
    download_count: int


class Release(TypedDict):
    tag_name: str
    published_at: str | None
    draft: bool
    assets: list[Asset]


def kind(name: str) -> tuple[str, str] | None:
    """The (platform, format) of a desktop asset, or None for other assets."""
    if not name.startswith("Onyx"):
        return None
    for suffix, platform, fmt in KINDS:
        if name.endswith(suffix):
            return (platform, fmt) if platform else None
    return None


def fetch_releases(repo: str) -> list[Release]:
    """Every release of `repo`, through the GitHub CLI (it reads GH_TOKEN)."""
    pages: list[list[Release]] = json.loads(
        subprocess.check_output(
            [
                "gh",
                "api",
                "--paginate",
                "--slurp",
                f"repos/{repo}/releases?per_page=100",
            ],
            text=True,
        )
    )
    return [release for page in pages for release in page]


def report(releases: Iterable[Release]) -> str:
    by_format: dict[tuple[str, str], int] = defaultdict(int)
    rows: list[tuple[str, str, Mapping[str, int], int]] = []
    feed_total = 0
    for release in releases:
        if release["draft"]:
            continue
        per_platform: dict[str, int] = defaultdict(int)
        feed = 0
        for asset in release["assets"]:
            count = asset["download_count"]
            if asset["name"] == FEED:
                feed += count
                continue
            found = kind(asset["name"])
            if found is None:
                continue
            per_platform[found[0]] += count
            by_format[found] += count
        if per_platform or feed:
            published = (release["published_at"] or "")[:10]
            rows.append((release["tag_name"], published, per_platform, feed))
            feed_total += feed

    rows.sort(key=lambda row: row[1], reverse=True)
    total = sum(by_format.values())
    lines = [
        "## Desktop app downloads",
        "",
        "From the `download_count` of GitHub release assets. The counts include "
        "automated downloads (mirrors, scanners, CI), so treat them as an upper "
        "bound, not as installs. Signatures (`.sig`) are not counted. "
        f"`{FEED}` downloads are update checks, not new installs.",
        "",
        f"Total installer and update-archive downloads: **{total:,}**",
        "",
        "### By platform and format",
        "",
        "| Platform | Format | Downloads |",
        "|---|---|---:|",
    ]
    for (platform, fmt), count in sorted(
        by_format.items(), key=lambda item: (PLATFORMS.index(item[0][0]), -item[1])
    ):
        lines.append(f"| {platform} | {fmt} | {count:,} |")
    lines += [
        "",
        "### By release",
        "",
        "| Release | Published | " + " | ".join(PLATFORMS) + f" | Total | `{FEED}` |",
        "|---|---|" + "---:|" * (len(PLATFORMS) + 2),
    ]
    for tag, published, per_platform, feed in rows:
        counts = [per_platform.get(p, 0) for p in PLATFORMS]
        cells = " | ".join(f"{c:,}" for c in counts)
        lines.append(f"| {tag} | {published} | {cells} | {sum(counts):,} | {feed:,} |")
    platform_totals = [
        sum(c for (p, _), c in by_format.items() if p == platform)
        for platform in PLATFORMS
    ]
    cells = " | ".join(f"**{c:,}**" for c in platform_totals)
    lines.append(f"| **All** | | {cells} | **{total:,}** | **{feed_total:,}** |")
    return "\n".join(lines) + "\n"


def main() -> None:
    sys.stdout.write(report(fetch_releases(os.environ["GITHUB_REPOSITORY"])))


if __name__ == "__main__":
    main()
