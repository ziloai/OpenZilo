# Documentation deployment

The build source SHA identifies an SDK revision. It does not identify the assembled
site: a push and a release for the same SDK commit produce different archives.

`docs.yml` serializes assembly and publishing. It preserves release snapshots,
commits the assembled site to `docs-site`, and passes that real archive commit as
`pages_build_version` through the Pages REST API. This avoids deploy-pages #383
without overriding reserved `GITHUB_*` variables. OIDC and the job's `pages: write`
permission are still required. The uploaded artifact ID comes from the upload step.

The archive is saved before deployment, so a failed deployment can be retried
without losing release history. Archive presence means desired content exists;
it does not certify that Pages is serving it.

After the Pages API reports success, `tools/verify_docs.py` compares HTTP content
hashes for `versions.json`, the root redirect and the Chinese/English homepages
of stable, release and development channels. Propagation is retried for at most
ten minutes. A stale placeholder or a missing release fails the publishing job.

Tests:

```sh
node --test tests/test_docs_deployment.cjs
uv run python -m unittest discover -s tests -p 'test_docs_*.py' -v
```
