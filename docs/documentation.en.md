# Maintaining documentation

--8<-- "docs/_includes/devices.en.md"

Keep documentation in the repository's Markdown files. Zensical builds `docs/`, `wiki/`, and project information into one website using its built-in modern theme, without custom CSS or a second manually maintained copy.

## Local preview

```bash
uv sync --locked --group docs
uv run --group docs python tools/build_docs.py
uv run --group docs python tools/check_docs.py
uv run python -m http.server 8000 --directory build/docs/html
```

Open `http://localhost:8000/`. The build generates Chinese and English sites and treats warnings as errors. After editing Markdown, rebuild and refresh your browser. Generated HTML stays in `build/docs/html/` and is not committed.

## Pages and translations

Edit the existing Markdown. Register new pages and their language sources in `PAGES` in `tools/build_docs.py`, then add them to the appropriate `navigation()` group and home-page links. The build rejects unregistered Markdown pages.

User-facing pages require separate Chinese and English sources. English pages do not fall back to Chinese content. The build checks English output for untranslated Chinese and compares section levels, table counts and code-block types in paired developer guides.

`zensical.toml` holds shared theme and Markdown extension settings. The build generates `/zh-CN/` and `/en/` separately. Zensical's built-in language menu links to the matching article. Each language has its own navigation and search without a multilingual plugin.

## Documentation organization

The home page serves SDK users: installation and quick start come first, followed by feature guides. Device instructions and protocol details come later.

- `sdk-quickstart.*.md` contains the first complete connection example.
- `sdk-<feature>.*.md` owns the call order, API details, examples and limitations for that feature.
- `python-sdk.*.md` is the API index, `sdk-data-types.*.md` documents returned fields, and `sdk-errors.*.md` documents exceptions.
- Keep installation, CLI, firmware differences and physical device operation separate from the feature guides.

`docs/sdk-section-redirects.json` preserves the former manual’s section URLs. Update its mapping when moving an old section; the generated targets are checked after building.

## Device applicability notes

Each SDK document includes `docs/_includes/devices.en.md` below its title; Chinese documents include `devices.zh-CN.md`. The note states that the document applies to OpenZilo Q. Display it once per page, without repeating it inside feature admonitions.

## Feature version notes

Use the theme's built-in admonitions. The following versions demonstrate syntax only; they do not describe an actual API's release history:

```markdown
!!! tip "Available since SDK v0.6.0"

    Explain the feature and how to use it.

!!! warning "Deprecated since SDK v0.8.0"

    Use `new_method()` instead. Removal is planned for SDK v1.0.0.

!!! danger "Removed in SDK v1.0.0"

    Use `new_method()` instead and link to the migration instructions.
```

Place the note immediately after the feature heading. Deprecated APIs remain available; mark removal only after the API is actually removed. Label planned removals explicitly, and omit an undecided version or date. Document SDK versions separately from firmware requirements. Do not infer introduction versions from Git commit dates.

Maintain shared requirements in `docs/_includes/features.zh-CN.md` and `features.en.md`. Include a section with PyMdown Snippets:

```markdown
;--8<-- "docs/_includes/features.en.md:recording-control"
```

Use HTML comments to mark shared sections, with matching names in both languages:

```markdown
<!-- ;--8<-- [start:recording-control] -->
!!! note "Remote recording requirements"

    This usage requires firmware **V2.001.0002.0001 or later**.
<!-- ;--8<-- [end:recording-control] -->
```

The semicolon before the scissors in this page's source escapes the example; omit it in an actual include. Missing files or sections fail the build. Before a specific usage, state “This usage requires firmware V2.001.0002.0001 or later”. For changed behavior in existing features, describe V2.001.0002.0000 and V2.001.0002.0001 separately. Keep SDK introduction versions separate. Keep model names, version numbers and parameter ranges consistent between translations.

## Documentation versions

`docs/release.toml` specifies the documentation target and release status without changing the SDK package version. The current target is v0.6.1; `status = "upcoming"` marks preview documentation and displays an unreleased notice. When preparing the release, update the package version and change the status to `released` in the same commit.

Shared feature notes say “Planned for SDK v0.6.1”; a release build renders them as “Available since SDK v0.6.1”. This conversion applies only to the current target, preserving historical versions for other features.

There is no historical version menu yet. Snapshots can be built from Git tags into separate directories; firmware requirements remain documented on the relevant feature pages.

## GitHub Pages

`.github/workflows/docs.yml` builds both languages and checks local links for pushes and pull requests. Deployment runs only for the default branch after a successful build.

A repository administrator must first choose **Settings → Pages → Build and deployment → Source → GitHub Actions**. Local builds do not change this setting or publish the site.

Relative links support both the `/OpenZilo/` project path and custom domains. The artifact includes both languages' search indexes and `.nojekyll`. Builds clean previous output so obsolete pages do not ship after changing generators.

Only `build/docs/html/` is deployed. Use placeholder device addresses and exclude private recordings, firmware artifacts and credentials.
