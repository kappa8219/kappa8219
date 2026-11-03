import unittest
from datetime import datetime, timezone

from update_starred_projects import (
    build_full_list,
    build_mermaid,
    build_readme_section,
    recently_released,
)


class StarredProjectsTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 3, tzinfo=timezone.utc)
        self.edges = [
            {
                "starredAt": "2026-11-02T00:00:00Z",
                "node": {
                    "nameWithOwner": "owner/recent",
                    "url": "https://github.com/owner/recent",
                    "stargazerCount": 1234,
                    "primaryLanguage": {"name": "Python"},
                    "latestRelease": {
                        "name": "v2.0",
                        "tagName": "v2.0",
                        "publishedAt": "2026-11-01T00:00:00Z",
                        "url": "https://github.com/owner/recent/releases/tag/v2.0",
                    },
                },
            },
            {
                "starredAt": "2026-10-02T00:00:00Z",
                "node": {
                    "nameWithOwner": "owner/old",
                    "url": "https://github.com/owner/old",
                    "stargazerCount": 5,
                    "primaryLanguage": {"name": "Go"},
                    "latestRelease": {
                        "name": "v1.0",
                        "tagName": "v1.0",
                        "publishedAt": "2025-11-02T00:00:00Z",
                        "url": "https://github.com/owner/old/releases/tag/v1.0",
                    },
                },
            },
            {"starredAt": "2026-09-02T00:00:00Z", "node": {"nameWithOwner": "owner/no-release", "latestRelease": None}},
        ]

    def test_filters_to_latest_release_in_rolling_year(self):
        matches = recently_released(self.edges, now=self.now)
        self.assertEqual(["owner/recent"], [edge["node"]["nameWithOwner"] for edge in matches])

    def test_mermaid_groups_projects_by_language_and_escapes_labels(self):
        self.edges[0]["node"]["nameWithOwner"] = 'owner/a "quoted" [repo]'
        graph = build_mermaid([self.edges[0]], total_starred=3)
        self.assertIn("flowchart TB", graph)
        self.assertIn("Python · 1", graph)
        self.assertIn("&quot;quoted&quot;", graph)
        self.assertIn("&#91;repo&#93;", graph)

    def test_full_list_includes_release_details_and_links(self):
        output = build_full_list([self.edges[0]], total_starred=3)
        self.assertIn("[owner/recent](https://github.com/owner/recent)", output)
        self.assertIn("[v2.0](https://github.com/owner/recent/releases/tag/v2.0)", output)
        self.assertIn("1,234", output)

    def test_readme_summary_links_to_full_list(self):
        section = build_readme_section([self.edges[0]], total_starred=3)
        self.assertIn("most recently starred of 1 starred repositories", section)
        self.assertIn("3 starred repositories checked", section)
        self.assertIn("./starred-projects.md", section)


if __name__ == "__main__":
    unittest.main()
