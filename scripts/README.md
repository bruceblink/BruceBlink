# Public profile snapshot / 公开数据速览

The two profile READMEs use native Markdown tables: no third-party statistics
service, remote image, tracking pixel, or JavaScript is needed to display them.
The language table is collapsed to keep the profile compact.

## Scope and calculation

- **Repositories:** public repositories owned by `bruceblink`, excluding forks,
  including archived repositories and this profile repository. Organization-owned
  projects are outside the scope. This is a repository count, not a claim of
  original authorship of all code.
- **Stars:** sum of `stargazers_count` on that same set, not stars given to others.
- **Followers:** `followers` on the public account; it is not filtered by repository.
- **Primary languages:** each included repository counts once using GitHub's
  `language` field. `null` is shown separately as Unspecified / 未标注. These are
  repository counts, not code-byte percentages, proficiency, or current work.
- **Time:** `updated_at` is UTC at the end of a successful collection, not the
  last code contribution. GitHub's endpoints are not an atomic snapshot; counts
  can change during collection.

Only these unauthenticated GitHub REST API endpoints are read:

- [Get a user](https://docs.github.com/en/rest/users/users#get-a-user):
  `https://api.github.com/users/bruceblink`
- [List repositories for a user](https://docs.github.com/en/rest/repos/repos#list-repositories-for-a-user):
  `https://api.github.com/users/bruceblink/repos?type=owner&sort=full_name&direction=asc&per_page=100&page=N`

Every page is fetched until a short/empty page. Unique repository IDs and the
total public repository count (including forks) before/after pagination are
checked before aggregation. Missing/invalid fields, unexpected private metadata,
duplicates, count mismatches, network errors, or rate limits fail the run instead
of producing partial statistics. No private-repository endpoint or user PAT is
used. Only aggregate data is stored in `dashboard/public-profile.json`.

## Refresh and validation

Python 3.11+ and its standard library are sufficient; there are no pip dependencies.

```sh
python3 -m unittest discover -s tests -v
python3 scripts/update_public_profile.py
```

The updater replaces only `public-profile` marker blocks and the JSON snapshot.
All responses are collected and all outputs rendered before any file is written.
API/validation failures leave the last successful files intact. CI commits only
after the entire update command succeeds, so a filesystem failure cannot publish
a partial update either.

The update workflow runs daily at 06:23 UTC or manually on `main`, only in
`bruceblink/BruceBlink`. GitHub may delay scheduled runs or disable schedules on
inactive repositories. Read the visible timestamp to judge freshness. Before the
PR is merged, the committed snapshot is the initial successful collection; the
schedule is not active for this change yet.

PR tests have `contents: read`; they have no write token or secrets. The trusted
update job has only `contents: write`, using this repository's built-in
`GITHUB_TOKEN` for its final push. Checkout credentials are not persisted, no token
is passed to the collector, and automatic commits use `github-actions[bot]`.
Only the two READMEs and JSON snapshot are staged. Pushes are never forced.
Repository rules can block direct bot pushes; in that case the workflow fails
and keeps the previously published snapshot. GitHub does not support restricting
`contents: write` to individual file paths, so the staged-path allowlist and
trusted branch guard provide the narrower operational scope.

The idle WakaTime and activity README workflows have been retired: neither had
matching sections in the current README, and this dashboard needs no external
service credentials. The separate existing snake animation workflow is unchanged
and is not a source for these metrics.

## 中文说明

两份 README 使用原生 Markdown 表格，语言明细默认折叠；无第三方统计卡或远程图片。
仓库和 Stars 只统计本人拥有的公开、非 fork 仓库，包括归档项目及本个人主页仓库，
不含组织名下项目。Followers 是账号公开关注者数。主要语言按每个仓库计一次，
未标注的单列；这不代表代码字节占比、当前工作重点或能力，也不宣称所有代码均为原创。

采集不携带认证信息，只访问以上公开 API，完整分页并校验数量后才更新。
更新时间为成功采集结束时的 UTC 时间。API 不提供跨请求的原子快照，采集期间的数据
可能变化；请求、限流、分页或校验失败时不发布部分统计，保留上次成功数据。
合并后计划每日更新；调度可能延迟或因仓库不活跃停用，请以显示时间判断新鲜度。
自动写入只在本仓库 main 分支使用内置 GITHUB_TOKEN，提交身份为 GitHub Actions bot，
不需要用户 PAT。仓库规则若阻止自动推送，工作流会失败，已发布快照保持不变。
