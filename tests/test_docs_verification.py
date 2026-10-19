# SPDX-License-Identifier: MPL-2.0
"""A successful Pages API response must not hide stale HTTP content."""
import json
from pathlib import Path
import tempfile
import unittest
from urllib.error import HTTPError
from urllib.parse import urlsplit

from tools.verify_docs import expected_pages, verify


class DocumentationVerificationTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.site = Path(folder.name)
        (self.site / 'versions.json').write_text(json.dumps({
            'stable': 'v0.6.1', 'versions': ['stable', 'v0.6.1', 'dev'],
            'commits': {'v0.6.1': 'a' * 40, 'dev': 'b' * 40}}))
        (self.site / 'index.html').write_text('<html>redirect to stable</html>')
        for channel in ('stable', 'v0.6.1', 'dev'):
            for locale in ('zh-CN', 'en'):
                page = self.site / channel / locale / 'index.html'
                page.parent.mkdir(parents=True)
                page.write_text(f'<html><article>{channel} {locale}</article></html>')
        self.clock = 0
        self.paths = []

    def sleep(self, duration):
        self.clock += duration

    def fetch(self, url, timeout):
        path = urlsplit(url).path.removeprefix('/docs/')
        self.paths.append(path)
        self.assertGreater(timeout, 0)
        return (self.site / path).read_bytes()

    def check(self, fetch=None):
        verify(self.site, 'https://example.github.io/docs/', timeout_s=3, interval_s=1,
               fetch_bytes=fetch or self.fetch, now=lambda: self.clock, sleep=self.sleep)

    def test_verifies_metadata_default_and_both_languages_in_all_channels(self):
        self.check()
        self.assertEqual(set(self.paths), set(expected_pages(self.site)))
        self.assertEqual(len(self.paths), 8)

    def test_old_metadata_fails_even_after_pages_api_success(self):
        def stale(url, timeout):
            if 'versions.json?' in url:
                return b'{"stable":null,"versions":["dev"]}'
            return self.fetch(url, timeout)
        with self.assertRaisesRegex(RuntimeError, 'versions.json'):
            self.check(stale)
        self.assertEqual(self.clock, 3)

    def test_placeholder_with_correct_metadata_is_not_accepted(self):
        def stale(url, timeout):
            if '/stable/zh-CN/' in url:
                return b'<html>No stable documentation</html>'
            return self.fetch(url, timeout)
        with self.assertRaisesRegex(RuntimeError, 'stable/zh-CN/index.html'):
            self.check(stale)

    def test_missing_version_route_is_not_accepted(self):
        def missing(url, timeout):
            if '/v0.6.1/en/' in url:
                raise HTTPError(url, 404, 'Not found', {}, None)
            return self.fetch(url, timeout)
        with self.assertRaisesRegex(RuntimeError, '404'):
            self.check(missing)

    def test_cache_propagation_retries_then_succeeds(self):
        def delayed(url, timeout):
            return b'old' if self.clock < 2 else self.fetch(url, timeout)
        self.check(delayed)
        self.assertEqual(self.clock, 2)

    def test_placeholder_in_incoming_stable_is_rejected_before_network(self):
        (self.site / 'stable/en/index.html').write_text('<html>placeholder</html>')
        with self.assertRaisesRegex(ValueError, 'placeholder'):
            self.check()
        self.assertEqual(self.paths, [])

    def test_invalid_base_url_is_rejected(self):
        for url in ('http://example.com/', 'https://user:secret@example.com/', 'https://example.com/?x=1'):
            with self.assertRaises(ValueError):
                verify(self.site, url)
