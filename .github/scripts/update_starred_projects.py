#!/usr/bin/env python3
"""Refresh the profile's recently released starred-projects graph with gh."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

README_PATH = Path("README.md")
LIST_PATH = Path("starred-projects.md")
START_MARKER = "<!--START_SECTION:starred-projects-->"
END_MARKER = "<!--END_SECTION:starred-projects-->"
LOOKBACK_DAYS = 365
MAX_GRAPH_PROJECTS = 30

STARRED_QUERY = """
query($login: String!, $endCursor: String) {
  user(login: $login) {
    starredRepositories(
      first: 100
      after: $endCursor
      orderBy: {field: STARRED_AT, direction: DESC}
    ) {
      edges {
        starredAt
        node {
          nameWithOwner
          url
          stargazerCount
          primaryLanguage { name }
          latestRelease { name tagName publishedAt url }
        }
      }
      pageInfo { hasNextPage endCursor }
    }
  }
}
"""


def github_username() -> str:
    username = os.getenv("GITHUB_USERNAME")
    if not username:
        repository = os.getenv("GITHUB_REPOSITORY", "")
        username = repository.split("/", 1)[0]
    if not username or not re.fullmatch(r"[A-Za-z0-9-]+", username):
        raise RuntimeError("Set GITHUB_USERNAME to the GitHub account to read stars for")
    return username


def fetch_starred_repositories(username: str) -> list[dict[str, Any]]:
    command = [
        "gh",
        "api",
        "graphql",
        "--paginate",
        "-F",
        f"login={username}",
        "-f",
        f"query={STARRED_QUERY}",
        "--jq",
        ".data.user.starredRepositories.edges[]",
    ]
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise RuntimeError("GitHub CLI (`gh`) is required to fetch starred repositories") from exc
    except subprocess.CalledProcessError as exc:
        message = exc.stderr.strip() or f"gh api exited with status {exc.returncode}"
        raise RuntimeError(f"Could not fetch starred repositories: {message}") from exc

    edges = []
    for line in result.stdout.splitlines():
        if line.strip():
            edge = json.loads(line)
            if isinstance(edge, dict) and isinstance(edge.get("node"), dict):
                edges.append(edge)
    return edges


def parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def recently_released(
    edges: list[dict[str, Any]], now: datetime | None = None, lookback_days: int = LOOKBACK_DAYS
) -> list[dict[str, Any]]:
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=lookback_days)
    matches = []
    for edge in edges:
        node = edge.get("node") or {}
        release = node.get("latestRelease")
        published_at = release.get("publishedAt") if isinstance(release, dict) else None
        if not published_at:
            continue
        try:
            if parse_timestamp(published_at) >= cutoff:
                matches.append(edge)
        except ValueError:
            continue
    return matches


def mermaid_label(value: str) -> str:
    """Escape untrusted API text for a quoted Mermaid flowchart label."""
    return (
        value.replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("[", "&#91;")
        .replace("]", "&#93;")
        .replace("\r", " ")
        .replace("\n", " ")
    )


def build_mermaid(edges: list[dict[str, Any]], total_starred: int) -> str:
    selected = edges[:MAX_GRAPH_PROJECTS]
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in selected:
        node = edge["node"]
        language = (node.get("primaryLanguage") or {}).get("name") or "Other"
        groups[language].append(edge)

    lines = [
        "```mermaid",
        "flowchart TB",
        "  classDef hub fill:#ddf4ff,stroke:#54aeff,color:#0969da;",
        "  classDef language fill:#f6f8fa,stroke:#d0d7de,color:#24292f;",
        "  classDef project fill:#ffffff,stroke:#d0d7de,color:#24292f;",
        (
            f'  hub(("⭐ Showing {len(selected)} of {len(edges)} matching projects; '
            f'{total_starred} stars checked"))'
        ),
        "  class hub hub;",
    ]

    if not selected:
        lines.extend(
            [
                '  empty["No matching starred repositories"]',
                "  hub --> empty",
                "  class empty project;",
            ]
        )
    else:
        for group_index, language in enumerate(sorted(groups), start=1):
            language_id = f"lang{group_index}"
            projects = groups[language]
            lines.append(
                f'  {language_id}["{mermaid_label(language)} · {len(projects)}"]'
            )
            lines.append(f"  class {language_id} language;")
            lines.append(f"  hub --> {language_id}")
            for project_index, edge in enumerate(projects, start=1):
                node = edge["node"]
                project_id = f"p{group_index}_{project_index}"
                repo = mermaid_label(node.get("nameWithOwner", "Unknown repository"))
                release = node.get("latestRelease") or {}
                release_date = release.get("publishedAt", "")[:10]
                label = f"{repo} · {release_date}" if release_date else repo
                lines.append(f'  {project_id}["{label}"]')
                lines.append(f"  {language_id} --> {project_id}")
                lines.append(f"  class {project_id} project;")

    lines.append("```")
    return "\n".join(lines)


def build_readme_section(edges: list[dict[str, Any]], total_starred: int) -> str:
    shown = min(len(edges), MAX_GRAPH_PROJECTS)
    list_link = "[Complete filtered list](./starred-projects.md)"
    if edges:
        summary = (
            f"_Showing the {shown} most recently starred of {len(edges)} starred repositories "
            f"whose latest release was published in the past {LOOKBACK_DAYS} days "
            f"({total_starred} starred repositories checked). {list_link}._"
        )
    else:
        summary = (
            f"_No starred repositories among {total_starred} checked had a release in the past "
            f"{LOOKBACK_DAYS} days. {list_link}._"
        )
    return f"{summary}\n\n{build_mermaid(edges, total_starred)}"


def update_readme(section: str) -> None:
    readme = README_PATH.read_text(encoding="utf-8")
    if readme.count(START_MARKER) != 1 or readme.count(END_MARKER) != 1:
        raise RuntimeError("README must contain exactly one pair of starred-project markers")
    before, rest = readme.split(START_MARKER, 1)
    _, after = rest.split(END_MARKER, 1)
    README_PATH.write_text(
        f"{before}{START_MARKER}\n{section}\n{END_MARKER}{after}", encoding="utf-8"
    )


def markdown_cell(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("[", "\\[")
        .replace("]", "\\]")
        .replace("\r", " ")
        .replace("\n", " ")
    )


def build_full_list(edges: list[dict[str, Any]], total_starred: int) -> str:
    lines = [
        "# Starred projects with a release in the last year",
        "",
        (
            f"Latest release within the past {LOOKBACK_DAYS} days; filtered from "
            f"{total_starred} starred repositories and sorted by most recently starred."
        ),
        "",
        "| Project | Latest release | Released | Language | Stars |",
        "| --- | --- | --- | --- | ---: |",
    ]
    for edge in edges:
        node = edge["node"]
        release = node.get("latestRelease") or {}
        repo = node.get("nameWithOwner", "Unknown repository")
        repo_url = node.get("url", "")
        release_tag = release.get("tagName") or release.get("name") or "release"
        release_url = release.get("url") or repo_url
        published_at = release.get("publishedAt", "")
        released = published_at[:10] if published_at else "Unknown"
        language = (node.get("primaryLanguage") or {}).get("name") or "—"
        stars = node.get("stargazerCount", 0)
        lines.append(
            "| "
            f"[{markdown_cell(repo)}]({repo_url}) | "
            f"[{markdown_cell(release_tag)}]({release_url}) | "
            f"{released} | {markdown_cell(language)} | {stars:,} |"
        )
    if not edges:
        lines.append("| _No matching starred repositories._ | — | — | — | — |")
    return "\n".join(lines) + "\n"


def main() -> int:
    username = github_username()
    edges = fetch_starred_repositories(username)
    matches = recently_released(edges)
    update_readme(build_readme_section(matches, len(edges)))
    LIST_PATH.write_text(build_full_list(matches, len(edges)), encoding="utf-8")
    print(
        f"Updated README graph with {min(len(matches), MAX_GRAPH_PROJECTS)} of "
        f"{len(matches)} matching projects ({len(edges)} starred repositories checked)."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, json.JSONDecodeError) as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1) from exc
