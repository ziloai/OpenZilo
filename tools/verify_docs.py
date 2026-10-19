# SPDX-License-Identifier: MPL-2.0
"""Verify that Pages serves this exact assembled archive, including stable."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import time
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def expected_pages(site):
    metadata = json.loads((site / 'versions.json').read_text(encoding='utf-8'))
    paths = ['versions.json', 'index.html']
    channels = ['stable'] + metadata['versions']
    for channel in dict.fromkeys(channels):
        for locale in ('zh-CN', 'en'):
            paths.append(f'{channel}/{locale}/index.html')
    result = {}
    for path in paths:
        data = (site / path).read_bytes()
        if path.startswith('stable/') and metadata['stable'] and b'<article' not in data:
            raise ValueError('Stable archive contains a placeholder instead of documentation')
        result[path] = sha256(data).hexdigest()
    return result


def fetch(url, timeout):
    request = Request(url, headers={'Cache-Control': 'no-cache', 'User-Agent': 'OpenZilo-docs-verifier'})
    with urlopen(request, timeout=timeout) as response:
        return response.read()


def verify(site, url, *, timeout_s=600, interval_s=10, fetch_bytes=fetch,
           now=time.monotonic, sleep=time.sleep):
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or not parsed.netloc or parsed.query or parsed.fragment
            or parsed.username or parsed.password):
        raise ValueError('Expected an HTTPS Pages base URL without query or credentials')
    if timeout_s <= 0 or interval_s <= 0:
        raise ValueError('Verification timeouts must be positive')
    expected = expected_pages(site)
    deadline = now() + timeout_s
    last_error = 'No response'
    while now() < deadline:
        try:
            for path, digest in expected.items():
                remaining = deadline - now()
                if remaining <= 0:
                    raise TimeoutError('Verification deadline reached')
                # A content-derived query helps caches, but matching bytes is mandatory.
                remote = fetch_bytes(f'{url.rstrip("/")}/{path}?docs_sha256={digest}', min(15, remaining))
                if sha256(remote).hexdigest() != digest:
                    raise ValueError(f'Pages still serves different content: {path}')
            print(f'Verified {len(expected)} live documentation entry points against the archive.')
            return
        except (URLError, OSError, ValueError) as error:
            last_error = str(error)
            print(f'Waiting for Pages content: {last_error}', flush=True)
        remaining = deadline - now()
        if remaining > 0:
            sleep(min(interval_s, remaining))
    raise RuntimeError(f'Pages did not serve the expected archive within {timeout_s}s: {last_error}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site', type=Path, required=True)
    parser.add_argument('--url', required=True)
    parser.add_argument('--timeout', type=float, default=600)
    args = parser.parse_args()
    verify(args.site, args.url, timeout_s=args.timeout)


if __name__ == '__main__':
    main()
