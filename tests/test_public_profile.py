"""Offline tests for complete, public-only snapshots and safe README updates."""

import copy
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from urllib.error import HTTPError


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/update_public_profile.py"
SPEC = importlib.util.spec_from_file_location("public_profile", SCRIPT)
profile = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(profile)


def repo(number, **overrides):
    result = {
        "id": number,
        "owner": {"login": "bruceblink"},
        "private": False,
        "fork": False,
        "archived": False,
        "stargazers_count": 1,
        "language": "Go",
    }
    result.update(overrides)
    return result


def user(count, followers=7):
    return {"login": "bruceblink", "public_repos": count, "followers": followers}


class FakeAPI:
    def __init__(self, repositories, before=None, after=None, fail_page=None):
        self.repositories = repositories
        self.before = before or user(len(repositories))
        self.after = after or self.before
        self.fail_page = fail_page
        self.calls = []
        self.user_calls = 0

    def __call__(self, url):
        self.calls.append(url)
        if url == profile.API:
            self.user_calls += 1
            return copy.deepcopy(self.before if self.user_calls == 1 else self.after)
        prefix = f"{profile.API}/repos?type=owner&sort=full_name&direction=asc&per_page=100&page="
        if not url.startswith(prefix):
            raise AssertionError(f"Unexpected endpoint: {url}")
        page = int(url.removeprefix(prefix))
        if page == self.fail_page:
            raise HTTPError(url, 403, "Rate limit exceeded", {}, None)
        return copy.deepcopy(self.repositories[(page - 1) * 100:page * 100])


class CollectorTests(unittest.TestCase):
    def test_http_request_is_unauthenticated_even_with_token_environment(self):
        with mock.patch.dict("os.environ", {"GITHUB_TOKEN": "must-not-be-used", "GH_TOKEN": "must-not-be-used"}):
            with mock.patch.object(profile.urllib.request, "urlopen", return_value=io.StringIO('{"ok": true}')) as request:
                self.assertEqual(profile.fetch_json(profile.API), {"ok": True})
        sent = request.call_args.args[0]
        self.assertEqual(sent.full_url, "https://api.github.com/users/bruceblink")
        self.assertNotIn("authorization", {key.lower() for key in sent.headers})
        self.assertNotIn("must-not-be-used", str(sent.headers))
        self.assertEqual(request.call_args.kwargs["timeout"], 30)

    def test_paginates_beyond_one_page(self):
        api = FakeAPI([repo(number) for number in range(101)])
        snapshot = profile.collect(api)
        self.assertEqual(snapshot["repositories"], 101)
        self.assertEqual(snapshot["stars"], 101)
        self.assertEqual(len(api.calls), 4)
        self.assertTrue(api.calls[2].endswith("page=2"))
        self.assertEqual(api.user_calls, 2)

    def test_full_page_requires_following_empty_page(self):
        api = FakeAPI([repo(number) for number in range(100)])
        self.assertEqual(profile.collect(api)["repositories"], 100)
        self.assertTrue(api.calls[2].endswith("page=2"))

    def test_excludes_forks_includes_archives_and_counts_primary_language(self):
        snapshot = profile.collect(FakeAPI([
            repo(1, stargazers_count=4),
            repo(2, fork=True, stargazers_count=999, language="Rust"),
            repo(3, archived=True, stargazers_count=2, language="Elixir"),
            repo(4, stargazers_count=0, language=None),
            repo(5, stargazers_count=3),
        ]))
        self.assertEqual(snapshot["repositories"], 4)
        self.assertEqual(snapshot["archived_repositories"], 1)
        self.assertEqual(snapshot["stars"], 9)
        self.assertEqual(snapshot["followers"], 7)
        self.assertEqual(snapshot["primary_languages"], [
            {"name": "Go", "repositories": 2},
            {"name": "Elixir", "repositories": 1},
        ])
        self.assertEqual(snapshot["without_primary_language"], 1)
        self.assertEqual(snapshot["scope"], {
            "visibility": "public", "owner_only": True, "forks": False, "archived": True,
        })
        self.assertRegex(snapshot["updated_at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

    def test_empty_account(self):
        snapshot = profile.collect(FakeAPI([]))
        self.assertEqual(snapshot["repositories"], 0)
        self.assertEqual(snapshot["primary_languages"], [])
        self.assertIn("| Unspecified | 0 |", profile.render(snapshot))

    def test_rejects_count_mismatch_before_or_after_collection(self):
        for before, after in [(user(2), user(1)), (user(1), user(2))]:
            with self.subTest(before=before, after=after), self.assertRaises(ValueError):
                profile.collect(FakeAPI([repo(1)], before=before, after=after))

    def test_rejects_duplicate_across_pages(self):
        repositories = [repo(number) for number in range(100)] + [repo(0)]
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            profile.collect(FakeAPI(repositories))

    def test_rejects_private_foreign_and_malformed_metadata(self):
        invalid = [
            {"private": True},
            {"owner": {"login": "someone-else"}},
            {"fork": 1},
            {"archived": "false"},
            {"stargazers_count": -1},
            {"stargazers_count": True},
            {"id": "123"},
            {"language": []},
            {"language": " "},
        ]
        for overrides in invalid:
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                profile.collect(FakeAPI([repo(1, **overrides)]))

    def test_rejects_invalid_profile_and_error_payload(self):
        with self.assertRaises(ValueError):
            profile.collect(FakeAPI([], before={"login": "someone-else"}))
        responses = iter([user(0), {"message": "API unavailable"}])
        with self.assertRaisesRegex(ValueError, "repository page"):
            profile.collect(lambda _url: next(responses))


class OutputTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "dashboard").mkdir()
        self.original = {}
        for filename in ("README.md", "README.zh-CN.md"):
            text = f"Original {filename}\n\n{profile.START}\nold snapshot\n{profile.END}\n\nUntouched footer 中文\n"
            (self.root / filename).write_text(text, encoding="utf-8")
            self.original[filename] = text.encode("utf-8")
        filename = "dashboard/public-profile.json"
        (self.root / filename).write_bytes(b'{"old": true}\n')
        self.original[filename] = b'{"old": true}\n'

    def assert_original_files_unchanged(self):
        for filename, content in self.original.items():
            self.assertEqual((self.root / filename).read_bytes(), content, filename)

    def test_second_page_api_failure_preserves_all_outputs(self):
        api = FakeAPI([repo(number) for number in range(101)], fail_page=2)
        with self.assertRaises(HTTPError):
            profile.update(self.root, api)
        self.assert_original_files_unchanged()

    def test_incomplete_collection_preserves_all_outputs(self):
        with self.assertRaises(ValueError):
            profile.update(self.root, FakeAPI([repo(1)], after=user(2)))
        self.assert_original_files_unchanged()

    def test_bad_second_readme_markers_preserve_all_outputs(self):
        path = self.root / "README.zh-CN.md"
        path.write_text("No markers\n", encoding="utf-8")
        self.original["README.zh-CN.md"] = b"No markers\n"
        with self.assertRaises(ValueError):
            profile.update(self.root, FakeAPI([repo(1)]))
        self.assert_original_files_unchanged()

    def test_successful_outputs_match_json_and_preserve_surrounding_text(self):
        profile.update(self.root, FakeAPI([repo(1, language=None), repo(2, archived=True)]))
        snapshot = json.loads((self.root / "dashboard/public-profile.json").read_text())
        self.assertEqual(snapshot["repositories"], 2)
        self.assertEqual(snapshot["stars"], 2)
        for filename, chinese in [("README.md", False), ("README.zh-CN.md", True)]:
            result = (self.root / filename).read_text()
            original = self.original[filename].decode("utf-8")
            before, rest = original.split(profile.START)
            _, after = rest.split(profile.END)
            self.assertEqual(result, before + profile.render(snapshot, chinese) + after)
            self.assertIn("| 2 | 2 | 7 |", result)

    def test_language_names_cannot_add_html_or_markdown_table_rows(self):
        language = '<script>[link](url)|*x*_`\\\nnext'
        snapshot = profile.collect(FakeAPI([repo(1, language=language)]))
        rendered = profile.render(snapshot)
        self.assertNotIn("<script>", rendered)
        self.assertNotIn("[link]", rendered)
        self.assertIn("&lt;script&gt;", rendered)
        self.assertIn(r"\|", rendered)
        self.assertEqual(rendered.count("\n"), profile.render(profile.collect(FakeAPI([repo(1)]))).count("\n"))

    def test_rejects_missing_duplicate_and_reversed_markers(self):
        invalid = ["no markers", profile.START + profile.END + profile.END, profile.END + profile.START]
        for text in invalid:
            with self.subTest(text=text), self.assertRaises(ValueError):
                profile.replace_section(text, "new")


class CommittedSnapshotTests(unittest.TestCase):
    def test_committed_snapshot_matches_both_readmes_and_language_totals(self):
        root = SCRIPT.parents[1]
        snapshot = json.loads((root / "dashboard/public-profile.json").read_text(encoding="utf-8"))
        self.assertEqual(snapshot["owner"], profile.OWNER)
        self.assertEqual(snapshot["scope"], {
            "visibility": "public", "owner_only": True, "forks": False, "archived": True,
        })
        language_total = sum(item["repositories"] for item in snapshot["primary_languages"])
        self.assertEqual(language_total + snapshot["without_primary_language"], snapshot["repositories"])
        for filename, chinese in [("README.md", False), ("README.zh-CN.md", True)]:
            text = (root / filename).read_text(encoding="utf-8")
            self.assertEqual(profile.replace_section(text, profile.render(snapshot, chinese)), text)


if __name__ == "__main__":
    unittest.main()
