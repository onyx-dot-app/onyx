"""Build the docs audit manifest.

Usage: python audit/build_manifest.py > audit/manifest.json

For every MDX page: nav tab, title, word count, images (with a coarse
classification), feature-map components, last git change, and orphan flag.
"""

import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

# docs path prefix -> feature-map components (.agents/feature-map/components/*.md in onyx)
COMPONENT_MAP = [
    (
        "admins/connectors",
        [
            "connectors",
            "connector-capability-checks",
            "cc-pairs-and-creds",
            "indexing-pipeline",
            "permission-sync",
        ],
    ),
    ("admins/ai_models", ["llm-providers", "llm-gateway", "document-index"]),
    (
        "admins/actions",
        [
            "tools-framework",
            "web-search",
            "image-generation",
            "code-execution",
            "voice",
            "mcp-and-custom-tools",
        ],
    ),
    ("admins/agents", ["agents-personas", "chat-preferences"]),
    (
        "admins/plugins",
        ["plugins", "mcp-and-custom-tools", "craft-external-apps", "craft-admin"],
    ),
    (
        "admins/user_management",
        ["access-control", "auth-and-identity", "authorization"],
    ),
    ("admins/permissions", ["access-control", "authorization"]),
    (
        "admins/managing_features",
        [
            "editions-and-gating",
            "whitelabelling-and-theme",
            "notifications",
            "chat-preferences",
        ],
    ),
    ("admins/analytics", ["observability"]),
    ("admins/auditing", ["observability"]),
    ("admins/billing", ["billing", "rate-and-usage-limits"]),
    (
        "admins/advanced_configs",
        ["editions-and-gating", "rate-and-usage-limits", "background-jobs"],
    ),
    ("admins/getting_started", ["auth-and-identity", "llm-providers", "connectors"]),
    (
        "overview/core_features",
        [
            "core-chat-loop",
            "chat-frontend",
            "internal-search",
            "projects",
            "citations",
            "file-store-and-user-files",
            "agents-personas",
        ],
    ),
    (
        "overview/onyx_anywhere",
        [
            "slack-bot",
            "discord-bot",
            "desktop-widget-extensions",
            "mobile-app",
            "mcp-server",
            "onyx-api",
        ],
    ),
    ("overview/getting_started", ["chat-frontend", "core-chat-loop"]),
    ("developers/api_reference", ["onyx-api"]),
    ("developers", ["onyx-api", "mcp-server"]),
    ("deployment/authentication", ["auth-and-identity"]),
    ("deployment", ["editions-and-gating", "multi-tenancy", "background-jobs"]),
    ("security", ["auth-and-identity", "access-control", "observability"]),
    (
        "agent-wiki",
        [
            "craft-admin",
            "craft-sessions",
            "craft-sandboxes",
            "craft-scheduled-tasks",
            "skills",
        ],
    ),
]

IMG_RE = re.compile(
    r'(?:!\[[^\]]*\]\(([^)\s]+)|<(?:img|Frame|Image|video)[^>]*src=["\']([^"\']+))'
)


def classify_image(path: str) -> str:
    p = path.lstrip("/")
    if p.startswith("assets/changelog/"):
        return "changelog"
    if p.startswith(("assets/logo/", "assets/icons/")):
        return "brand"
    if p.startswith("assets/deployment/setup_guides/"):
        return "cloud-console"
    if re.match(r"assets/admins/connectors/[^/]+/", p):
        return (
            "connector-mixed"  # vendor console or Onyx connector form; reviewer decides
        )
    if p.endswith(".svg"):
        return "diagram"
    return "onyx-ui"


def nav_pages(nav) -> dict:
    out = {}

    def walk(node, tab):
        if isinstance(node, str):
            out[node] = tab
        elif isinstance(node, list):
            for n in node:
                walk(n, tab)
        elif isinstance(node, dict):
            tab = node.get("tab", tab)
            for k in ("pages", "groups", "tabs"):
                if k in node:
                    walk(node[k], tab)

    walk(nav, None)
    return out


FEATURE_MAP_COMPONENTS = os.path.join(
    os.path.dirname(ROOT), ".agents", "feature-map", "components"
)


def check_component_map() -> None:
    """Fail when COMPONENT_MAP names a feature-map component that does not exist."""
    existing = {
        os.path.splitext(f)[0]
        for _, _, files in os.walk(FEATURE_MAP_COMPONENTS)
        for f in files
        if f.endswith(".md")
    }
    missing = sorted({c for _, comps in COMPONENT_MAP for c in comps} - existing)
    if missing:
        sys.exit(f"COMPONENT_MAP names missing feature-map components: {missing}")


def main() -> None:
    check_component_map()
    docs = json.load(open("docs.json"))
    in_nav = nav_pages(docs["navigation"])
    pages = []
    for root, _, files in os.walk("."):
        if "/.git" in root or "node_modules" in root or root.startswith("./audit"):
            continue
        for f in sorted(files):
            if not f.endswith(".mdx"):
                continue
            path = os.path.join(root, f)[2:]
            slug = path[:-4]
            text = open(path).read()
            m = re.search(r'^title:\s*["\']?(.*?)["\']?\s*$', text, re.MULTILINE)
            imgs = [a or b for a, b in IMG_RE.findall(text)]
            components = next(
                (c for prefix, c in COMPONENT_MAP if slug.startswith(prefix)), []
            )
            date = subprocess.run(
                ["git", "log", "-1", "--format=%cs", "--", path],
                capture_output=True,
                text=True,
            ).stdout.strip()
            pages.append(
                {
                    "page": path,
                    "tab": in_nav.get(slug),
                    "in_nav": slug in in_nav,
                    "title": m.group(1) if m else None,
                    "words": len(re.sub(r"<[^>]+>", "", text).split()),
                    "last_commit": date,
                    "components": components,
                    "images": [{"src": i, "kind": classify_image(i)} for i in imgs],
                }
            )
    json.dump({"pages": pages}, sys.stdout, indent=1)


if __name__ == "__main__":
    main()
