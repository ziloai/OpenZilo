"""Checks for persistent documentation versions and the stable default."""
import json
from pathlib import Path
import tempfile
import unittest

from tools.assemble_docs import assemble, START


class DocumentationPublishingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.incoming = self.root / 'incoming'
        self.site = self.root / 'site'
        self.build('first')

    def build(self, text, extra=False):
        self.incoming.mkdir(exist_ok=True)
        (self.incoming / 'index.html').write_text('<html><a href="zh-CN/index.html">Docs</a></html>')
        pages = ['index', 'sdk/connection'] + (['sdk/new'] if extra else [])
        (self.incoming / 'documentation-pages.json').write_text(json.dumps({
            'languages': ['zh-CN', 'en'], 'pages': pages}))
        for locale in ('zh-CN', 'en'):
            for route in pages:
                page = self.incoming / locale / f'{route}.html'
                page.parent.mkdir(parents=True, exist_ok=True)
                page.write_text(f'<html><article>{text}</article></html>')

    def publish(self, version, commit='a'):
        assemble(self.site, self.incoming, version, commit * 40)

    def metadata(self):
        return json.loads((self.site / 'versions.json').read_text())

    def test_first_development_build_does_not_become_stable(self):
        self.publish('dev')
        self.assertIsNone(self.metadata()['stable'])
        self.assertIn('url=stable/index.html', (self.site / 'index.html').read_text())
        self.assertIn('No stable documentation', (self.site / 'stable/en/index.html').read_text())
        self.assertFalse((self.site / 'stable/en/sdk/connection.html').exists())

    def test_development_updates_preserve_stable_and_releases(self):
        self.publish('v0.6.1')
        self.build('new development')
        self.publish('dev', 'b')
        self.assertIn('first', (self.site / 'stable/en/index.html').read_text())
        self.assertIn('first', (self.site / 'v0.6.1/en/index.html').read_text())
        self.assertIn('new development', (self.site / 'dev/en/index.html').read_text())

    def test_highest_release_wins_even_when_older_release_arrives_later(self):
        self.publish('v0.6.10')
        self.build('older release')
        self.publish('v0.6.2', 'b')
        self.assertEqual(self.metadata()['stable'], 'v0.6.10')
        self.assertIn('first', (self.site / 'stable/en/index.html').read_text())
        self.assertTrue((self.site / 'v0.6.2/en/index.html').exists())

    def test_version_menu_keeps_language_article_and_falls_back(self):
        self.publish('v0.6.1')
        self.build('development', extra=True)
        self.publish('dev', 'b')
        page = (self.site / 'dev/en/sdk/connection.html').read_text()
        self.assertIn('../../../stable/en/sdk/connection.html', page)
        new_page = (self.site / 'dev/en/sdk/new.html').read_text()
        self.assertIn('../../../v0.6.1/en/index.html', new_page)
        self.assertEqual(page.count(START), 1)
        self.publish('dev', 'b')
        self.assertEqual((self.site / 'v0.6.1/en/index.html').read_text().count(START), 1)

    def test_moved_tag_is_rejected_without_changing_stable(self):
        self.publish('v0.6.1')
        with self.assertRaisesRegex(ValueError, 'immutable'):
            self.publish('v0.6.1', 'b')
        self.assertEqual(self.metadata()['commits']['v0.6.1'], 'a' * 40)

    def test_release_rerun_preserves_snapshot(self):
        self.publish('v0.6.1')
        self.build('different build environment')
        self.publish('v0.6.1')
        self.assertIn('first', (self.site / 'v0.6.1/en/index.html').read_text())

    def test_invalid_release_and_path_are_rejected(self):
        for version in ('../stable', 'stable', 'v0.6.1rc1', 'v01.6.1'):
            with self.subTest(version=version), self.assertRaises(ValueError):
                self.publish(version)

    def test_symlinks_are_rejected(self):
        (self.incoming / 'outside').symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symlinks'):
            self.publish('dev')


if __name__ == '__main__':
    unittest.main()
