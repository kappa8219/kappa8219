#!/usr/bin/env python3
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict

README_PATH = "README.md"
START_MARKER = "<!--START_SECTION:participated-projects-->"
END_MARKER = "<!--END_SECTION:participated-projects-->"
REST_API = "https://api.github.com"
GRAPHQL_API = "https://api.github.com/graphql"


def api_get_json(url: str, token: str) -> object:
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub REST request failed: {exc.code} {body}") from exc


def graphql_query(token: str, query: str, variables: dict) -> dict:
    payload = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    req = urllib.request.Request(
        GRAPHQL_API,
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub GraphQL request failed: {exc.code} {body}") from exc

    if "errors" in data:
        raise RuntimeError(f"GitHub GraphQL errors: {data['errors']}")
    return data


def recent_public_activity(login: str, token: str, max_pages: int = 10) -> list[tuple[str, int]]:
    counts = defaultdict(int)
    profile_repo = f"{login}/{login}"
    for page in range(1, max_pages + 1):
        query = urllib.parse.urlencode({"per_page": 100, "page": page})
        url = f"{REST_API}/users/{login}/events/public?{query}"
        events = api_get_json(url, token)
        if not isinstance(events, list) or not events:
            break

        for event in events:
            repo = (event.get("repo") or {}).get("name")
            if repo and repo != profile_repo:
                counts[repo] += 1

    return sorted(counts.items(), key=lambda it: (it[1], it[0].lower()), reverse=True)


def contributed_repositories(login: str, token: str) -> list[tuple[str, int]]:
    query = """
    query($login: String!) {
      user(login: $login) {
        repositoriesContributedTo(
          first: 100
          includeUserRepositories: true
          contributionTypes: [COMMIT, ISSUE, PULL_REQUEST, PULL_REQUEST_REVIEW, REPOSITORY]
          orderBy: {field: PUSHED_AT, direction: DESC}
        ) {
          nodes {
            nameWithOwner
          }
        }
      }
    }
    """
    data = graphql_query(token, query, {"login": login})
    nodes = (
        (((data.get("data") or {}).get("user") or {}).get("repositoriesContributedTo") or {}).get("nodes")
        or []
    )
    profile_repo = f"{login}/{login}"
    return [
        (node["nameWithOwner"], 0)
        for node in nodes
        if node and node.get("nameWithOwner") and node["nameWithOwner"] != profile_repo
    ]


def build_section(rows: list[tuple[str, int]], limit: int = 10) -> str:
    if not rows:
        return "_No participation data found._"

    lines = ["```mermaid", "graph TD", "  projects[Projects]"]
    for idx, (repo, _) in enumerate(rows[:limit], start=1):
        lines.append(f'  p{idx}["{repo}"]')
        lines.append(f"  projects --> p{idx}")
    lines.append("```")
    return "\n".join(lines)


def update_readme(section_body: str) -> None:
    with open(README_PATH, "r", encoding="utf-8") as f:
        readme = f.read()

    if START_MARKER not in readme or END_MARKER not in readme:
        raise RuntimeError("README markers not found")

    before, rest = readme.split(START_MARKER, 1)
    _, after = rest.split(END_MARKER, 1)
    new_readme = f"{before}{START_MARKER}\n{section_body}\n{END_MARKER}{after}"

    with open(README_PATH, "w", encoding="utf-8") as f:
        f.write(new_readme)


def main() -> int:
    token = os.getenv("GITHUB_TOKEN")
    repo = os.getenv("GITHUB_REPOSITORY", "")
    if not token:
        print("GITHUB_TOKEN is required", file=sys.stderr)
        return 1
    if not repo or "/" not in repo:
        print("GITHUB_REPOSITORY must be in owner/repo format", file=sys.stderr)
        return 1

    login = repo.split("/")[0]
    rows = recent_public_activity(login, token)
    if not rows:
        rows = contributed_repositories(login, token)

    section = build_section(rows)
    update_readme(section)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
