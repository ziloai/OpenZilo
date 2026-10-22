"""Build both languages from the maintained Markdown files, without source copies.

Run with: uv run --group docs python tools/build_docs.py
"""
import argparse
from html import escape
import json
from pathlib import Path
import posixpath
import re
import shutil
import subprocess
import sys
import runpy

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

import yaml
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
# (website page, Chinese source, English source).
PAGES = [
    ("index", "docs/index.md", "docs/index.en.md"),
    ("overview", "README.zh-CN.md", "README.md"),
    ("guide/index", "wiki/Home-zh-CN.md", "wiki/Home.md"),
    ("guide/first-use", "wiki/First-Use-zh-CN.md", "wiki/First-Use.md"),
    ("guide/buttons", "wiki/Buttons-and-Modes-zh-CN.md", "wiki/Buttons-and-Modes.md"),
    ("guide/leds", "wiki/LED-Indicators-zh-CN.md", "wiki/LED-Indicators.md"),
    ("guide/firmware", "wiki/Firmware-Updates-zh-CN.md", "wiki/Firmware-Updates.md"),
    ("developer/sdk", "docs/python-sdk.zh-CN.md", "docs/python-sdk.en.md"),
    ("sdk/install", "docs/sdk-install.zh-CN.md", "docs/sdk-install.en.md"),
    ("sdk/quickstart", "docs/sdk-quickstart.zh-CN.md", "docs/sdk-quickstart.en.md"),
    ("sdk/connection", "docs/sdk-connection.zh-CN.md", "docs/sdk-connection.en.md"),
    ("sdk/device-info", "docs/sdk-device-info.zh-CN.md", "docs/sdk-device-info.en.md"),
    ("sdk/time-sync", "docs/sdk-time-sync.zh-CN.md", "docs/sdk-time-sync.en.md"),
    ("sdk/logs", "docs/sdk-logs.zh-CN.md", "docs/sdk-logs.en.md"),
    ("sdk/downloads", "docs/sdk-downloads.zh-CN.md", "docs/sdk-downloads.en.md"),
    ("sdk/live-audio", "docs/sdk-live-audio.zh-CN.md", "docs/sdk-live-audio.en.md"),
    ("sdk/audio-decoding", "docs/sdk-audio-decoding.zh-CN.md", "docs/sdk-audio-decoding.en.md"),
    ("sdk/imu", "docs/sdk-imu.zh-CN.md", "docs/sdk-imu.en.md"),
    ("sdk/events", "docs/sdk-events.zh-CN.md", "docs/sdk-events.en.md"),
    ("sdk/ota", "docs/sdk-ota.zh-CN.md", "docs/sdk-ota.en.md"),
    ("sdk/data-types", "docs/sdk-data-types.zh-CN.md", "docs/sdk-data-types.en.md"),
    ("sdk/protocol-tools", "docs/sdk-protocol-tools.zh-CN.md", "docs/sdk-protocol-tools.en.md"),
    ("sdk/migration", "docs/sdk-migration.zh-CN.md", "docs/sdk-migration.en.md"),
    ("sdk/errors", "docs/sdk-errors.zh-CN.md", "docs/sdk-errors.en.md"),

    ("developer/cli", "docs/cli.zh-CN.md", "docs/cli.en.md"),
    ("developer/recording", "docs/recording-control.zh-CN.md", "docs/recording-control.md"),
    ("developer/compatibility", "docs/compatibility.zh-CN.md", "docs/compatibility.en.md"),
    ("developer/features", "docs/features.zh-CN.md", "docs/features.en.md"),
    ("developer/protocol", "docs/protocol.zh-CN.md", "docs/protocol.en.md"),
    ("developer/architecture", "docs/architecture.zh-CN.md", "docs/architecture.en.md"),
    ("developer/ai-tools", "docs/ai-tools.zh-CN.md", "docs/ai-tools.md"),
    ("contributing/index", "CONTRIBUTING.zh-CN.md", "CONTRIBUTING.md"),
    ("contributing/security", "SECURITY.zh-CN.md", "SECURITY.md"),
    ("contributing/agents", "AGENTS.md", "AGENTS.md"),
    ("contributing/claude", "CLAUDE.md", "CLAUDE.md"),
    ("contributing/gemini", "GEMINI.md", "GEMINI.md"),
    ("contributing/copilot", ".github/copilot-instructions.md", ".github/copilot-instructions.md"),
    ("reference/changelog", "CHANGELOG.md", "CHANGELOG.md"),
    ("reference/wiki-sidebar", "wiki/_Sidebar.md", "wiki/_Sidebar.en.md"),
    ("reference/wiki-entry", "wiki/OpenZilo-Documentation.md", "wiki/OpenZilo-Documentation.en.md"),
]
SOURCE_MAP = {source: page for page, *sources in PAGES for source in sources}
REPOSITORY = "https://github.com/ziloai/OpenZilo"
REFERENCE_PAGES = {"contributing/agents", "contributing/claude", "contributing/gemini",
                   "contributing/copilot", "reference/wiki-sidebar", "reference/wiki-entry", "reference/changelog"}


def document_url(target, source, page, locale):
    """Resolve repository and Wiki links into the staged site's stable routes."""
    parsed = urlsplit(target)
    fragment = f"#{parsed.fragment}" if parsed.fragment else ""
    if target.startswith("#") or parsed.scheme in ("mailto", "data"):
        return target
    path = unquote(parsed.path)
    if parsed.scheme:
        if parsed.netloc.lower() != "github.com":
            return target
        prefix = "/ziloai/openzilo/"
        if not path.lower().startswith(prefix):
            return target
        repo_path = path[len(prefix):]
        if repo_path.startswith("wiki"):
            name = repo_path.removeprefix("wiki").strip("/") or "Home"
            resolved = f"wiki/{name}.md"
        elif repo_path.startswith("blob/main/"):
            resolved = repo_path.removeprefix("blob/main/")
        else:
            return target
    else:
        if not path:
            return target
        resolved = posixpath.normpath(posixpath.join(posixpath.dirname(source), path))
    if resolved in SOURCE_MAP:
        if resolved.startswith("wiki/"):
            target_locale = "zh-CN" if "-zh-CN" in resolved else "en"
            if target_locale != locale:
                return posixpath.relpath(f"{target_locale}/{SOURCE_MAP[resolved]}.html",
                                         posixpath.dirname(f"{locale}/{page}")) + fragment
        return posixpath.relpath(SOURCE_MAP[resolved] + ".md", posixpath.dirname(page)) + fragment
    if resolved == "llms.txt":
        return posixpath.relpath("reference/llms.md", posixpath.dirname(page)) + fragment
    if resolved.startswith("docs/assets/"):
        return posixpath.relpath("assets/" + resolved.removeprefix("docs/assets/"), posixpath.dirname(page))
    if (ROOT / resolved).exists() and not resolved.startswith("../"):
        route = "tree/main/" if (ROOT / resolved).is_dir() else "blob/main/"
        return f"{REPOSITORY}/{route}{resolved}{fragment}"
    return target


def rewrite(text, source, page, locale):
    # Protect code fences: links shown as examples must remain literal.
    pieces = re.split(r"(^[ \t]*`{3,}.*?$[\s\S]*?^[ \t]*`{3,}[ \t]*$)", text, flags=re.M)
    for index in range(0, len(pieces), 2):
        part = pieces[index]
        def markdown_url(match):
            url = document_url(match[2], source, page, locale)
            # Other language builds are checked after both sites are generated.
            # Cross-language routes point to the other generated HTML site.
            if not urlsplit(url).scheme and ".html" in url and not match[1].startswith("!"):
                return f'<a href="{escape(url, quote=True)}">{match[1][1:-2]}</a>'
            return match[1] + url + match[3]
        part = re.sub(r"(!?\[[^\]\n]*\]\()([^\s)]+)(\))", markdown_url, part)
        def html_url(match):
            url = document_url(match[2], source, page, locale)
            if not urlsplit(url).scheme:
                url = re.sub(r"\.md(?=#|$)", ".html", url)
            return match[1] + url + match[3]
        part = re.sub(r'(\b(?:href|src)=\")([^\"]+)(\")', html_url, part)
        pieces[index] = part
    return "".join(pieces)


def stage(destination, locale, release):
    destination.mkdir(parents=True, exist_ok=True)
    index = 1 if locale == "zh-CN" else 2
    for row in PAGES:
        page, source = row[0], row[index]
        text = (ROOT / source).read_text(encoding="utf-8")
        if source.startswith("wiki/") and page not in REFERENCE_PAGES:
            # The site's language control replaces the Wiki's duplicate row.
            text = re.sub(r"^\[English\]\([^\n]+\n", "", text, flags=re.M)
        text = rewrite(text, source, page, locale)
        if source.startswith("wiki/_Sidebar"):
            text = "# Wiki navigation\n\n" + text
        elif source.endswith("AGENTS.md"):
            text = "# Repository instructions\n\n" + text
        elif source in ("CLAUDE.md", "GEMINI.md", ".github/copilot-instructions.md") and not text.startswith("# "):
            text = f"# {Path(source).stem} instructions\n\n" + text
        # README's HTML hero remains in the repository; the site's overview uses
        # its existing Markdown body with a normal page title.
        if source.startswith("README"):
            start = text.index("OpenZilo 是" if locale == "zh-CN" else "OpenZilo is")
            text = ("# OpenZilo 平台\n\n" if locale == "zh-CN" else "# OpenZilo platform\n\n") + text[start:]
        fallback = locale == "zh-CN" and row[1] == row[2] and page in REFERENCE_PAGES
        if fallback:
            message = "本页保留英文项目说明。"
            first, sep, rest = text.partition("\n")
            text = first + f'\n\n!!! note\n\n    {message}\n' + sep + rest
        if page in REFERENCE_PAGES:
            text = "---\nsearch:\n  exclude: true\n---\n\n" + text
        if release["status"] == "upcoming" and page not in REFERENCE_PAGES:
            title, newline, rest = text.partition("\n")
            version = release["version"]
            notice = (f'!!! warning "v{version} 预览文档"\n\n    本文档包含计划随 SDK v{version} 发布的功能，已发布版本可能尚未提供。\n'
                      if locale == "zh-CN" else
                      f'!!! warning "v{version} preview documentation"\n\n    This documentation includes features planned for SDK v{version} that may not be available in released SDK versions.\n')
            text = title + "\n\n" + notice + newline + rest
        if page == "developer/sdk":
            sections = json.loads((ROOT / "docs/sdk-section-redirects.json").read_text(encoding="utf-8"))[locale]
            destinations = {}
            for anchor, target in sections.items():
                url = document_url(target, source, page, locale)
                url = re.sub(r"\.md(?=#|$)", ".html", url)
                if url != f"sdk.html#{anchor}":
                    destinations[anchor] = url
            # Preserve bookmarked section URLs after the large manual was split.
            text += "\n<script>\n" + "const sdkSections = " + json.dumps(destinations, ensure_ascii=False) + ";\n"
            text += "const section = decodeURIComponent(window.location.hash.slice(1));\nif (sdkSections[section]) window.location.replace(sdkSections[section]);\n</script>\n"
        target = destination / f"{page}.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    content = (ROOT / "llms.txt").read_text(encoding="utf-8")
    (destination / "reference/llms.md").write_text(
        "---\nsearch:\n  exclude: true\n---\n\n# Documentation index for agents\n\n" + rewrite(content.replace("# OpenZilo\n", "", 1), "llms.txt", "reference/llms", locale), encoding="utf-8")
    shutil.copytree(ROOT / "docs/assets", destination / "assets", dirs_exist_ok=True)


def check_coverage():
    for page, chinese, english in PAGES:
        if chinese == english and page not in REFERENCE_PAGES:
            raise SystemExit(f"Missing separate English translation: {page}")
    discovered = {str(path.relative_to(ROOT)) for folder in (ROOT / "docs", ROOT / "wiki") for path in folder.glob("*.md")}
    discovered.update(str(p.relative_to(ROOT)) for p in ROOT.glob("*.md"))
    missing = discovered - set(SOURCE_MAP)
    if missing:
        raise SystemExit("Markdown pages missing from documentation navigation: " + ", ".join(sorted(missing)))


def check_snippets():
    """Fail before publishing if a shared requirement disappears in one language."""
    marker = r"<!-- --8<-- \[start:([\w-]+)\] -->(.*?)<!-- --8<-- \[end:\1\] -->"
    shared = {}
    for locale in ("zh-CN", "en"):
        shared[locale] = dict(re.findall(marker, (ROOT / f"docs/_includes/features.{locale}.md").read_text(encoding="utf-8"), re.S))
    if shared["zh-CN"].keys() != shared["en"].keys():
        raise SystemExit("Shared feature sections differ between languages")
    for section in shared["en"]:
        versions = lambda text: re.findall(r"(?<![\w.])[vV]?\d+(?:\.\d+)+(?:\.dev\d+)?", text)
        if versions(shared["zh-CN"][section]) != versions(shared["en"][section]):
            raise SystemExit(f"Feature versions differ between languages: {section}")
    for source in SOURCE_MAP:
        text = (ROOT / source).read_text(encoding="utf-8")
        for target in re.findall(r'^--8<-- "([^"\n]+)"', text, re.M):
            filename, _, section = target.partition(":")
            path = ROOT / filename
            if path.parent != ROOT / "docs/_includes" or not path.is_file():
                raise SystemExit(f"Unknown shared Markdown: {source}: {target}")
            if section and section not in dict(re.findall(marker, path.read_text(encoding="utf-8"), re.S)):
                raise SystemExit(f"Missing shared section: {source}: {target}")


class UnicodeSlug:
    """Use PyMdown's Unicode heading URLs, including Chinese section names."""


class ConfigDumper(yaml.SafeDumper):
    pass


ConfigDumper.add_representer(UnicodeSlug, lambda dumper, value: dumper.represent_mapping(
    "tag:yaml.org,2002:python/object/apply:pymdownx.slugs.slugify", {"kwds": {"case": "lower"}}))


def configured_url(base, locale):
    return base["site_url"].rstrip("/") + f"/{locale}/"


def navigation(source, locale):
    groups = [
        ("开始使用", "Get started", ["sdk/install", "sdk/quickstart", "developer/cli"]),
        ("按功能使用", "Use SDK features", ["sdk/connection", "sdk/device-info", "developer/compatibility", "sdk/time-sync",
         "developer/recording", "sdk/downloads", "sdk/live-audio", "sdk/audio-decoding", "sdk/imu", "sdk/events", "sdk/logs", "sdk/ota"]),
        ("API 参考", "API reference", ["developer/sdk", "sdk/data-types", "sdk/errors"]),
        ("版本与兼容", "Versions and compatibility", ["developer/features", "sdk/migration"]),
        ("设备与底层资料", "Device and protocol", ["guide/index", "guide/first-use", "guide/buttons", "guide/leds", "guide/firmware",
         "developer/protocol", "developer/architecture", "sdk/protocol-tools"]),
        ("参与开发", "Development", ["developer/ai-tools", "contributing/index", "contributing/security", "overview"]),
    ]
    groups.append(("Releases", "Releases", ["reference/changelog"]))
    nav = [{"首页" if locale == "zh-CN" else "Home": "index.md"}]
    for chinese, english, routes in groups:
        entries = []
        for route in routes:
            title = re.search(r"^# (.+)", (source / f"{route}.md").read_text(encoding="utf-8"), re.M)[1]
            entries.append({title: f"{route}.md"})
        nav.append({chinese if locale == "zh-CN" else english: entries})
    return nav


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "build/docs/html")
    parser.add_argument("--channel", choices=("dev", "stable"), default=None,
                        help="Published URL prefix; omit for the standalone local preview")
    parser.add_argument("--release-tag", help="Validate a formal release tag against documentation and package versions")
    args = parser.parse_args()
    check_coverage()
    check_snippets()
    output = args.output.resolve()
    sources = ROOT / "build/docs/source"
    if (not output.is_relative_to(sources.parent) or sources.is_relative_to(output)
            or output.is_relative_to(sources) or output.is_relative_to(sources.parent / "_snippets")):
        raise SystemExit("Output must be a separate directory under build/docs/")
    release = tomllib.loads((ROOT / "docs/release.toml").read_text(encoding="utf-8"))["release"]
    version = release["version"]
    if not re.fullmatch(r"\d+\.\d+\.\d+", version) or release["status"] not in {"upcoming", "released"}:
        raise SystemExit("Document release must be a stable version with upcoming/released status")
    if args.release_tag:
        if args.release_tag != f"v{version}" or release["status"] != "released":
            raise SystemExit("A formal release requires matching vX.Y.Z tag and released documentation status")
    if args.channel == "stable" and not args.release_tag:
        raise SystemExit("The stable channel requires --release-tag")
    if release["status"] == "released":
        package_version = runpy.run_path(str(ROOT / "src/openzilo/_version.py"))["__version__"]
        if package_version != version:
            raise SystemExit(f"Released documentation {version} does not match SDK package {package_version}")
    # A clean output prevents old generator files and removed pages from shipping.
    if output.exists():
        shutil.rmtree(output)
    snippets = sources.parent / "_snippets/docs/_includes"
    if snippets.parent.parent.exists():
        shutil.rmtree(snippets.parent.parent)
    snippets.mkdir(parents=True, exist_ok=True)
    for snippet in (ROOT / "docs/_includes").glob("*.md"):
        text = snippet.read_text(encoding="utf-8")
        if release["status"] == "released":
            text = text.replace(f"计划于 SDK v{version} 提供", f"自 SDK v{version} 起提供")
            text = text.replace(f"Planned for SDK v{version}", f"Available since SDK v{version}")
        (snippets / snippet.name).write_text(text, encoding="utf-8")
    base = tomllib.loads((ROOT / "zensical.toml").read_text(encoding="utf-8"))["project"]
    if args.channel:
        prefix = args.release_tag if args.channel == "stable" else "dev"
        base["site_url"] = base["site_url"].rstrip("/") + f"/{prefix}/"
    for locale in ("zh-CN", "en"):
        source = sources / locale
        if source.exists():
            shutil.rmtree(source)
        stage(source, locale, release)
        config = json.loads(json.dumps(base))
        config.update(
            site_name=f"OpenZilo SDK v{version}" + ((" 预览" if locale == "zh-CN" else " Preview") if release["status"] == "upcoming" else ""),
            site_url=base["site_url"].rstrip("/") + f"/{locale}/",
            docs_dir=posixpath.relpath(source, sources.parent),
            site_dir=posixpath.relpath(output / locale, sources.parent),
            nav=navigation(source, locale),
            extra={"alternate": [
                {"name": "简体中文", "lang": "zh", "link": "__OPENZILO_ZH__"},
                {"name": "English", "lang": "en", "link": "__OPENZILO_EN__"},
            ]},
        )
        config["theme"]["language"] = "zh" if locale == "zh-CN" else "en"
        config["markdown_extensions"].extend([
            {"toc": {"permalink": True, "slugify": UnicodeSlug()}},
            {"pymdownx.snippets": {"base_path": ["_snippets"], "check_paths": True}},
        ])
        config_path = sources.parent / f"zensical-{locale}.yml"
        config_path.write_text(yaml.dump(config, Dumper=ConfigDumper, allow_unicode=True, sort_keys=False), encoding="utf-8")
        subprocess.run([sys.executable, "-m", "zensical", "build", "--strict", "--clean",
                        "--config-file", str(config_path)], cwd=sources.parent, check=True)
    # Use the built-in language menu, with a relative link to the same page.
    # Relative URLs also work under the /OpenZilo/ GitHub Pages project path.
    for locale in ("zh-CN", "en"):
        for html in (output / locale).rglob("*.html"):
            route = html.relative_to(output / locale).as_posix()
            text = html.read_text(encoding="utf-8")
            for other, marker in (("zh-CN", "__OPENZILO_ZH__"), ("en", "__OPENZILO_EN__")):
                target = output / other / route
                if not target.exists():
                    target = output / other / "index.html"
                href = escape(posixpath.relpath(target, html.parent), quote=True)
                text = re.sub(r'href="[^"]*' + marker + r'[^"]*"', lambda match: f'href="{href}"', text)
            if html.name == "404.html":
                prefix = urlsplit(configured_url(base, locale)).path
                text = re.sub(r'(\b(?:href|src)=")[^"]*',
                              lambda match: match[0].replace(prefix, "", 1) if match[0].startswith(match[1] + prefix) else match[0], text)
            html.write_text(text, encoding="utf-8")
    output.mkdir(parents=True, exist_ok=True)
    (output / ".nojekyll").touch()
    (output / "index.html").write_text(
        '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta http-equiv="refresh" content="0;url=zh-CN/index.html">'
        '<title>OpenZilo Documentation</title><a href="zh-CN/index.html">简体中文</a> · <a href="en/index.html">English</a></html>', encoding="utf-8")
    (output / "llms.txt").write_text((ROOT / "llms.txt").read_text(encoding="utf-8"), encoding="utf-8")
    (output / "documentation-pages.json").write_text(json.dumps(
        {"languages": ["zh-CN", "en"], "pages": [r[0] for r in PAGES] + ["reference/llms"]}, indent=2) + "\n", encoding="utf-8")
    print(f"Documentation built: {output}")


if __name__ == "__main__":
    main()
