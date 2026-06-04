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


def is_owned_by_user(repo_full_name: str, login: str) -> bool:
    owner = repo_full_name.split("/", 1)[0] if "/" in repo_full_name else ""
    return owner.lower() == login.lower()


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
    for page in range(1, max_pages + 1):
        query = urllib.parse.urlencode({"per_page": 100, "page": page})
        url = f"{REST_API}/users/{login}/events/public?{query}"
        events = api_get_json(url, token)
        if not isinstance(events, list) or not events:
            break

        for event in events:
            repo = (event.get("repo") or {}).get("name")
            if repo and not is_owned_by_user(repo, login):
                counts[repo] += 1

    return sorted(counts.items(), key=lambda it: (it[1], it[0].lower()), reverse=True)


def issue_comment_activity(
    login: str, token: str, max_pages: int = 10
) -> list[tuple[str, int]]:
    counts = defaultdict(int)
    query = f"commenter:{login} is:issue"
    for page in range(1, max_pages + 1):
        params = urllib.parse.urlencode(
            {"q": query, "per_page": 100, "page": page, "sort": "updated", "order": "desc"}
        )
        url = f"{REST_API}/search/issues?{params}"
        result = api_get_json(url, token)
        if not isinstance(result, dict):
            break

        items = result.get("items") or []
        if not isinstance(items, list) or not items:
            break

        for item in items:
            if not isinstance(item, dict):
                continue
            repository_url = item.get("repository_url")
            if not isinstance(repository_url, str) or "/repos/" not in repository_url:
                continue
            repo = repository_url.split("/repos/", 1)[1]
            if repo and not is_owned_by_user(repo, login):
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
    return [
        (node["nameWithOwner"], 0)
        for node in nodes
        if node and node.get("nameWithOwner") and not is_owned_by_user(node["nameWithOwner"], login)
    ]


def build_section(rows: list[tuple[str, int]], limit: int = 10) -> str:
    if not rows:
        return "_No participation data found._"

    top_rows = rows[:limit]
    max_count = max((count for _, count in top_rows), default=0)
    min_size = 12
    max_size = 28
    cols = 3

    lines = [
        "```mermaid",
        "graph TB",
        "  classDef tag fill:#f6f8fa,stroke:#d0d7de,color:#24292f;",
        "  linkStyle default stroke:transparent,stroke-width:0px;",
    ]
    node_ids = []
    for idx, (repo, count) in enumerate(top_rows, start=1):
        node_id = f"p{idx}"
        node_ids.append(node_id)
        if max_count > 0:
            size = min_size + int((count / max_count) * (max_size - min_size))
        else:
            size = min_size
        lines.append(f'  {node_id}["{repo}"]:::tag')
        lines.append(f"  style {node_id} font-size:{size}px")

    for i, node_id in enumerate(node_ids):
        if (i + 1) % cols != 0 and i + 1 < len(node_ids):
            lines.append(f"  {node_id} --- {node_ids[i + 1]}")
        if i + cols < len(node_ids):
            lines.append(f"  {node_id} --- {node_ids[i + cols]}")
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
    merged_counts = defaultdict(int)
    for repo_name, count in recent_public_activity(login, token):
        merged_counts[repo_name] += count
    for repo_name, count in issue_comment_activity(login, token):
        merged_counts[repo_name] += count

    rows = sorted(merged_counts.items(), key=lambda it: (it[1], it[0].lower()), reverse=True)
    if not rows:
        rows = contributed_repositories(login, token)

    section = build_section(rows)
    update_readme(section)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
