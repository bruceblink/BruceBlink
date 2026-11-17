#!/usr/bin/env python3
"""Generate a small public-only GitHub snapshot, using Python's standard library."""

import collections
import datetime as dt
import html
import json
from pathlib import Path
import sys
import urllib.request

OWNER = "bruceblink"
API = f"https://api.github.com/users/{OWNER}"
ROOT = Path(__file__).resolve().parents[1]
START = "<!-- public-profile:start -->"
END = "<!-- public-profile:end -->"


def fetch_json(url):
    # Intentionally unauthenticated: never read a PAT, GITHUB_TOKEN or /user/repos.
    request = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "BruceBlink-public-profile",
    })
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def nonnegative_int(value):
    if type(value) is not int or value < 0:
        raise ValueError("Expected a nonnegative integer from GitHub")
    return value


def validate_user(user):
    if not isinstance(user, dict) or user.get("login", "").lower() != OWNER:
        raise ValueError("Unexpected GitHub user")
    nonnegative_int(user["public_repos"])
    nonnegative_int(user["followers"])


def collect(fetch=fetch_json):
    user = fetch(API)
    validate_user(user)
    repos = []
    seen = set()
    for page in range(1, 1001):
        batch = fetch(f"{API}/repos?type=owner&sort=full_name&direction=asc&per_page=100&page={page}")
        if not isinstance(batch, list) or len(batch) > 100:
            raise ValueError("Invalid repository page")
        for repo in batch:
            if not isinstance(repo, dict) or repo.get("private") is not False:
                raise ValueError("Expected only public repository metadata")
            if repo.get("owner", {}).get("login", "").lower() != OWNER:
                raise ValueError("Unexpected repository owner")
            repo_id = nonnegative_int(repo["id"])
            if repo_id in seen:
                raise ValueError("Duplicate repository across pages; retry later")
            seen.add(repo_id)
            if type(repo["fork"]) is not bool or type(repo["archived"]) is not bool:
                raise ValueError("Invalid fork/archive flag")
            nonnegative_int(repo["stargazers_count"])
            language = repo["language"]
            if language is not None and (not isinstance(language, str) or not language.strip()):
                raise ValueError("Invalid primary language")
            repos.append(repo)
        if len(batch) < 100:
            break
    else:
        raise ValueError("Pagination limit reached; refusing a partial snapshot")

    # Counts catch truncation and common repo additions/deletions during pagination.
    # GitHub does not offer an atomic cross-endpoint snapshot.
    after = fetch(API)
    validate_user(after)
    if user["public_repos"] != len(repos) or after["public_repos"] != len(repos):
        raise ValueError("Public repository count changed or pagination incomplete; retry later")
    owned = [repo for repo in repos if not repo["fork"]]
    languages = collections.Counter(repo["language"] for repo in owned if repo["language"] is not None)
    return {
        "schema_version": 1,
        "owner": OWNER,
        "updated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "scope": {"visibility": "public", "owner_only": True, "forks": False, "archived": True},
        "sources": [API, f"{API}/repos?type=owner&sort=full_name&direction=asc&per_page=100"],
        "repositories": len(owned),
        "archived_repositories": sum(repo["archived"] for repo in owned),
        "stars": sum(repo["stargazers_count"] for repo in owned),
        "followers": after["followers"],
        "primary_languages": [
            {"name": name, "repositories": count}
            for name, count in sorted(languages.items(), key=lambda item: (-item[1], item[0]))
        ],
        "without_primary_language": sum(repo["language"] is None for repo in owned),
    }


def markdown_text(value):
    value = html.escape(value.replace("\n", " ").replace("\r", " "))
    for character in ("\\", "|", "`", "*", "_", "[", "]"):
        value = value.replace(character, "\\" + character)
    return value


def render(snapshot, chinese=False):
    stamp = snapshot["updated_at"].replace("T", " ").replace("Z", " UTC")
    if chinese:
        title = "公开数据速览"
        labels = "公开非 fork 仓库 | 这些仓库的 Stars | Followers"
        scope = f"范围：本人拥有的公开仓库，排除 fork，包含归档项目（{snapshot['archived_repositories']} 个）。Followers 为账号公开关注者数。"
        summary = "主要语言 · 按仓库数量"
        heading = "GitHub 主要语言 | 仓库数"
        unknown = "未标注"
        note = "每个仓库按 GitHub 标注的主要语言计数；不代表代码字节占比、当前工作重点或能力。"
        source = f"[公开 API 与统计口径](./scripts/README.md) · 最后成功采集：{stamp} · 计划每日更新，失败时保留旧数据。"
    else:
        title = "Public snapshot"
        labels = "Public non-fork repos | Stars on these repos | Followers"
        scope = f"Scope: public repositories I own, excluding forks and including archived projects ({snapshot['archived_repositories']}). Followers is the public account count."
        summary = "Primary languages · repository counts"
        heading = "GitHub primary language | Repositories"
        unknown = "Unspecified"
        note = "Each repository counts once by its GitHub primary language; this is not a share of code bytes, current work, or a measure of proficiency."
        source = f"[Public API & methodology](./scripts/README.md) · Last successful collection: {stamp} · Scheduled daily; failures retain the previous snapshot."
    rows = [f"| {markdown_text(item['name'])} | {item['repositories']} |" for item in snapshot["primary_languages"]]
    if snapshot["without_primary_language"] or not rows:
        rows.append(f"| {unknown} | {snapshot['without_primary_language']} |")
    return "\n".join([
        START, f"## {title}", "", f"| {labels} |", "| ---: | ---: | ---: |",
        f"| {snapshot['repositories']} | {snapshot['stars']} | {snapshot['followers']} |", "",
        scope, "", "<details>", f"<summary>{summary}</summary>", "",
        f"| {heading} |", "| --- | ---: |", *rows, "", note, "", "</details>", "", source, END,
    ])


def replace_section(text, section):
    if text.count(START) != 1 or text.count(END) != 1:
        raise ValueError("README must contain exactly one pair of public-profile markers")
    before, rest = text.split(START)
    _, after = rest.split(END)
    return before + section + after


def update(root=ROOT, fetch=fetch_json):
    snapshot = collect(fetch)
    # Prepare every output before touching any file. API/validation/render failures
    # leave all previous files intact. CI only commits after this command succeeds.
    outputs = {
        root / "README.md": replace_section((root / "README.md").read_text(encoding="utf-8"), render(snapshot)),
        root / "README.zh-CN.md": replace_section((root / "README.zh-CN.md").read_text(encoding="utf-8"), render(snapshot, True)),
        root / "dashboard/public-profile.json": json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n",
    }
    for path, content in outputs.items():
        path.write_text(content, encoding="utf-8")
    print(f"Updated public snapshot: {snapshot['repositories']} non-fork repos, {snapshot['stars']} stars, {snapshot['followers']} followers")


if __name__ == "__main__":
    try:
        update()
    except Exception as error:
        print(f"Public snapshot not updated: {error}", file=sys.stderr)
        sys.exit(1)
