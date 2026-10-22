"""Check every generated local URL, anchor, language switch, and public page."""
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

from markdown_it import MarkdownIt

ROOT = Path(__file__).resolve().parents[1] / "build/docs/html"


def shared_english_prose(chinese_text, english_text):
    """Find copied English explanations, excluding code, identifiers and examples."""
    markdown = MarkdownIt().enable("table")

    def paragraphs(text):
        result = set()
        for token in markdown.parse(text):
            if token.type != "inline" or not token.children:
                continue
            prose = " ".join(child.content for child in token.children if child.type == "text")
            prose = re.sub(r"\s+", " ", prose).strip()
            if not re.search(r"[\u3400-\u9fff]", prose) and len(re.findall(r"[A-Za-z][A-Za-z'-]*", prose)) >= 9:
                result.add(prose)
        return result

    return sorted(paragraphs(chinese_text) & paragraphs(english_text))


class Page(HTMLParser):
    def __init__(self, path):
        super().__init__(convert_charrefs=True)
        self.ids = set()
        self.links = []
        self.text = []
        self.alternates = {}
        self.language = None
        self.ignored_depth = 0
        self.feed(path.read_text(encoding="utf-8"))

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.ignored_depth += 1
        attrs = dict(attrs)
        if tag == "html":
            self.language = attrs.get("lang")
        if tag == "link" and attrs.get("rel") == "alternate":
            self.alternates[attrs.get("hreflang")] = attrs.get("href")
        if attrs.get("id"):
            self.ids.add(attrs["id"])
        for attr in ("href", "src"):
            if attrs.get(attr):
                self.links.append(attrs[attr])

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.ignored_depth = max(0, self.ignored_depth - 1)

    def handle_data(self, data):
        if not self.ignored_depth:
            self.text.append(data)


def main():
    pages = {p.resolve(): Page(p) for p in ROOT.rglob("*.html")}
    errors = set()
    if not pages:
        raise SystemExit("Documentation output is missing; run tools/build_docs.py first")
    for path, page in pages.items():
        if path.is_relative_to(ROOT / "en"):
            # The language selector is intentionally labelled in its own language.
            english_text = " ".join(page.text).replace("简体中文", "")
            chinese = re.search(r"[\u3400-\u9fff]", english_text)
            if chinese:
                excerpt = english_text[max(0, chinese.start()-30):chinese.end()+60]
                errors.add(f"Untranslated Chinese in {path.relative_to(ROOT)}: {excerpt!r}")
        for link in page.links:
            url = urlsplit(link)
            if url.scheme or url.netloc or link == "#":
                continue
            if url.path.startswith("/"):
                errors.add(f"{path.relative_to(ROOT)}: root-relative URL breaks project Pages: {link}")
                continue
            target = (path.parent / unquote(url.path)).resolve() if url.path else path
            if target.is_dir():
                target /= "index.html"
            if not target.is_relative_to(ROOT.resolve()) or not target.exists():
                errors.add(f"{path.relative_to(ROOT)}: missing target {link}")
            elif url.fragment and target in pages and unquote(url.fragment) not in pages[target].ids:
                errors.add(f"{path.relative_to(ROOT)}: missing anchor {link}")
    inventory = json.loads((ROOT / "documentation-pages.json").read_text())
    for locale in inventory["languages"]:
        for name in inventory["pages"]:
            path = ROOT / locale / f"{name}.html"
            if not path.exists():
                errors.add(f"Missing {locale} page: {name}")
    # Every article must switch to the matching article, rather than a language home page.
    for locale in inventory["languages"]:
        for name in inventory["pages"]:
            path = (ROOT / locale / f"{name}.html").resolve()
            if path not in pages:
                continue
            page = pages[path]
            expected_language = "zh" if locale == "zh-CN" else "en"
            if page.language != expected_language:
                errors.add(f"Wrong interface language: {locale}/{name}")
            for language, folder in (("zh", "zh-CN"), ("en", "en")):
                href = page.alternates.get(language)
                expected = (ROOT / folder / f"{name}.html").resolve()
                if not href or (path.parent / href).resolve() != expected:
                    errors.add(f"Language switch does not match article: {locale}/{name}: {language}")
        search = json.loads((ROOT / locale / "search.json").read_text(encoding="utf-8"))
        if search.get("config", {}).get("lang") != ["zh" if locale == "zh-CN" else "en"]:
            errors.add(f"Wrong search language: {locale}")
        searchable = {urlsplit(item["location"]).path for item in search.get("items", [])}
        for name in inventory["pages"]:
            if name.startswith("reference/") or name in {"contributing/agents", "contributing/claude", "contributing/gemini", "contributing/copilot"}:
                continue
            if f"{name}.html" not in searchable:
                errors.add(f"Article missing from search: {locale}/{name}")
        if locale == "en" and re.search(r"[\u3400-\u9fff]", json.dumps(search, ensure_ascii=False)):
            errors.add("Untranslated Chinese in English search index")
    # Each SDK and device article has one applicability note at the beginning.
    from build_docs import PAGES, REFERENCE_PAGES
    for route, chinese_source, english_source in PAGES:
        if route in REFERENCE_PAGES or not chinese_source.startswith(("docs/", "wiki/")):
            continue
        for locale in inventory["languages"]:
            path = (ROOT / locale / f"{route}.html").resolve()
            if path in pages:
                content = " ".join(pages[path].text)
                sentence = "本文档适用于  OpenZilo Q 。" if locale == "zh-CN" else "This document applies to  OpenZilo Q ."
                # Normalize HTML inline-element boundaries before counting the note.
                normalized = re.sub(r"\s+", "", content)
                expected = re.sub(r"\s+", "", sentence)
                if normalized.count(expected) != 1:
                    errors.add(f"Expected one device applicability note: {locale}/{route}")
    # The split manual retains old bookmarked fragments through a generated redirect.
    from build_docs import SOURCE_MAP
    repository = ROOT.parents[2]
    redirects = json.loads((repository / "docs/sdk-section-redirects.json").read_text(encoding="utf-8"))
    for locale, sections in redirects.items():
        for old, link in sections.items():
            target = urlsplit(link)
            route = SOURCE_MAP.get("docs/" + target.path)
            path = (ROOT / locale / f"{route}.html").resolve()
            if path not in pages or (target.fragment and unquote(target.fragment) not in pages[path].ids):
                errors.add(f"Broken former SDK section: {locale}#{old}: {link}")
    if any("dev0" in path.read_text(encoding="utf-8") for path in pages):
        errors.add("Development version exposed in public documentation")
    # Private engineering evidence is never part of the public documentation.
    if list(ROOT.rglob("compatibility-matrix.json")):
        errors.add("Local engineering matrix included in public output")
    for path in pages:
        text = path.read_text(encoding="utf-8")
        if "compatibility-matrix.json" in text:
            errors.add(f"Private engineering matrix linked from {path.relative_to(ROOT)}")
    # Full translations retain the sections, tables and code examples of their
    # counterpart. This catches missing sections as well as fallback pages.
    repository = ROOT.parents[2]
    markdown = MarkdownIt().enable("table")
    from build_docs import PAGES, REFERENCE_PAGES
    for route, chinese_source, english_source in PAGES:
        if route in REFERENCE_PAGES or chinese_source == english_source:
            continue
        chinese = repository / chinese_source
        english = repository / english_source
        name = route
        def structure(path):
            tokens = markdown.parse(path.read_text(encoding="utf-8"))
            return ([t.tag for t in tokens if t.type == "heading_open"],
                    sum(t.type == "table_open" for t in tokens),
                    [t.info.split()[0] if t.info else "" for t in tokens if t.type == "fence"])
        for copied in shared_english_prose(chinese.read_text(encoding="utf-8"), english.read_text(encoding="utf-8")):
            errors.add(f"English explanation copied into Chinese page: {name}: {copied[:120]!r}")
        if structure(chinese) != structure(english):
            errors.add(f"Translation structure differs: {name}")
    if errors:
        raise SystemExit("\n".join(sorted(errors)))
    print(f"Checked {len(pages)} HTML pages: local links, anchors, translations, matching language switches, search indexes and public output OK.")


if __name__ == "__main__":
    main()
