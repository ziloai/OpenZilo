"""Merge one checked documentation build into the persistent Pages archive."""
import argparse
from html import escape
from html.parser import HTMLParser
import json
from pathlib import Path
import posixpath
import re
import shutil
from urllib.parse import unquote, urlsplit

VERSION = re.compile(r"v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)")
START = '<!-- openzilo-versions -->'
END = '<!-- /openzilo-versions -->'


class Links(HTMLParser):
    def __init__(self, path):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.ids = set()
        self.feed(path.read_text(encoding='utf-8'))

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get('id'):
            self.ids.add(attrs['id'])
        for name in ('href', 'src'):
            if attrs.get(name):
                self.links.append(attrs[name])


def validate_site(site):
    pages = {p: Links(p) for p in site.rglob('*.html')}
    for path, page in pages.items():
        for href in page.links:
            url = urlsplit(href)
            if url.scheme or url.netloc or href == '#':
                continue
            if url.path.startswith('/'):
                raise ValueError(f'Root-relative link breaks project Pages: {path}: {href}')
            target = (path.parent / unquote(url.path)).resolve() if url.path else path
            if target.is_dir():
                target /= 'index.html'
            if not target.is_relative_to(site) or not target.exists():
                raise ValueError(f'Missing published link target: {path}: {href}')
            if url.fragment and target in pages and unquote(url.fragment) not in pages[target].ids:
                raise ValueError(f'Missing published anchor: {path}: {href}')


def redirect(path, target):
    path.parent.mkdir(parents=True, exist_ok=True)
    url = escape(target, quote=True)
    path.write_text(f'<!doctype html><html lang="en"><meta charset="utf-8">'
                    f'<meta http-equiv="refresh" content="0;url={url}">'
                    f'<title>OpenZilo SDK</title><a href="{url}">OpenZilo SDK documentation</a></html>', encoding='utf-8')


def assemble(site, incoming, version, commit):
    if version != 'dev' and not VERSION.fullmatch(version):
        raise ValueError('Expected dev or a formal vX.Y.Z release')
    if not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise ValueError('Expected a full Git commit SHA')
    if site == incoming or site in incoming.parents or incoming in site.parents:
        raise ValueError('Archive and incoming build must be separate directories')
    if any(p.is_symlink() for root in (site, incoming) for p in root.rglob('*')):
        raise ValueError('Documentation must not contain symlinks')
    manifest = json.loads((incoming / 'documentation-pages.json').read_text())
    for locale in manifest['languages']:
        for page in manifest['pages']:
            if not (incoming / locale / f'{page}.html').is_file():
                raise ValueError(f'Missing incoming page: {locale}/{page}')
    site.mkdir(parents=True, exist_ok=True)
    metadata_path = site / 'versions.json'
    metadata = json.loads(metadata_path.read_text()) if metadata_path.exists() else {'commits': {}}
    commits = metadata['commits']
    if any(name != 'dev' and not VERSION.fullmatch(name) for name in commits):
        raise ValueError('Invalid version in archive metadata')
    if version != 'dev' and version in commits and commits[version] != commit:
        raise ValueError(f'{version} already belongs to another commit; release snapshots are immutable')
    destination = site / version
    if version == 'dev' or version not in commits:
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(incoming, destination)
    commits[version] = commit
    releases = sorted((v for v in commits if v != 'dev'),
                      key=lambda v: tuple(map(int, VERSION.fullmatch(v).groups())), reverse=True)
    stable = releases[0] if releases else None
    stable_dir = site / 'stable'
    if stable_dir.exists():
        shutil.rmtree(stable_dir)
    if stable:
        shutil.copytree(site / stable, stable_dir)
    else:
        # Never label a development build as stable, even on the first deployment.
        for locale in ('zh-CN', 'en'):
            page = stable_dir / locale / 'index.html'
            page.parent.mkdir(parents=True, exist_ok=True)
            message = '尚无稳定版文档。' if locale == 'zh-CN' else 'No stable documentation has been published yet.'
            label = '查看开发版文档' if locale == 'zh-CN' else 'View development documentation'
            link = f'<p><a href="../../dev/{locale}/index.html">{label}</a></p>' if 'dev' in commits else ''
            page.write_text(f'<!doctype html><html lang="{locale}"><meta charset="utf-8">'
                            f'<title>OpenZilo SDK</title><h1>OpenZilo SDK</h1><p>{message}</p>{link}'
                            '<p><a href="../zh-CN/index.html">简体中文</a> · '
                            '<a href="../en/index.html">English</a></p></html>', encoding='utf-8')
        redirect(stable_dir / 'index.html', 'zh-CN/index.html')
    channels = (['stable'] if stable else []) + releases + (['dev'] if 'dev' in commits else [])
    for channel in channels:
        for locale in ('zh-CN', 'en'):
            for page in (site / channel / locale).rglob('*.html'):
                text = page.read_text(encoding='utf-8')
                text = re.sub(re.escape(START) + r'.*?' + re.escape(END), '', text, flags=re.S)
                route = page.relative_to(site / channel)
                links = []
                for other in channels:
                    target = site / other / route
                    if not target.is_file():
                        target = site / other / locale / 'index.html'
                    href = posixpath.relpath(target, page.parent)
                    label = (f'stable ({stable})' if other == 'stable' else
                             ('开发版' if locale == 'zh-CN' else 'Development') if other == 'dev' else other)
                    current = ' aria-current="page"' if channel == other else ''
                    links.append(f'<li><a href="{escape(href, quote=True)}"{current}>{label}</a></li>')
                title = '文档版本' if locale == 'zh-CN' else 'Documentation version'
                current_label = f'stable ({stable})' if channel == 'stable' else channel
                nav = (f'{START}<details><summary>{title}: {current_label}</summary>'
                       f'<ul>{"".join(links)}</ul></details>{END}')
                text, count = re.subn(r'(<article\b[^>]*>)', lambda m: m[0] + nav, text, count=1)
                if not count and page.name != '404.html':
                    raise ValueError(f'Missing article for version menu: {page}')
                page.write_text(text, encoding='utf-8')
    metadata.update(stable=stable, versions=channels)
    metadata_path.write_text(json.dumps(metadata, indent=2) + '\n', encoding='utf-8')
    redirect(site / 'index.html', 'stable/index.html')
    (site / '.nojekyll').touch()
    # Keep previously advertised unversioned article links usable.
    for locale in manifest['languages']:
        for route in manifest['pages']:
            old = site / locale / f'{route}.html'
            target = stable_dir / locale / f'{route}.html'
            if not target.is_file():
                target = stable_dir / locale / 'index.html'
            redirect(old, posixpath.relpath(target, old.parent))
    (site / 'llms.txt').write_text(
        '# OpenZilo SDK documentation\n\n'
        '[Stable documentation](stable/en/index.html) is the default.\n'
        + ('[Stable documentation index](stable/llms.txt)\n' if stable else '')
        + ('[Development documentation](dev/en/index.html)\n' if 'dev' in commits else ''),
        encoding='utf-8')
    validate_site(site)
    print(f'Assembled {version}; default: stable ({stable or "not yet published"})')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site', type=Path, required=True)
    parser.add_argument('--incoming', type=Path, required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--commit', required=True)
    args = parser.parse_args()
    assemble(args.site.resolve(), args.incoming.resolve(), args.version, args.commit)


if __name__ == '__main__':
    main()
