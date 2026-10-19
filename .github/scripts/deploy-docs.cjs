// Deploy a real documentation-archive commit, independently of the SDK commit.
// actions/deploy-pages uses GITHUB_SHA, which collides for push/release builds.
module.exports = async function deployDocs({github, context, core, archiveCommit,
  artifactId, now = Date.now, sleep = ms => new Promise(resolve => setTimeout(resolve, ms)),
  timeoutMs = 600000}) {
  if (!/^[0-9a-f]{40}$/.test(archiveCommit || '')) throw new Error('Invalid archive commit');
  const artifact = Number(artifactId);
  if (!Number.isSafeInteger(artifact) || artifact < 1) throw new Error('Invalid Pages artifact ID');
  const repository = {owner: context.repo.owner, repo: context.repo.repo};
  // The archive must be pushed before this call: Pages requires an existing SHA.
  await github.request('GET /repos/{owner}/{repo}/git/commits/{commit_sha}',
    {...repository, commit_sha: archiveCommit});
  const oidcToken = await core.getIDToken();
  core.setSecret(oidcToken);
  const {data: deployment} = await github.request('POST /repos/{owner}/{repo}/pages/deployments',
    {...repository, artifact_id: artifact, pages_build_version: archiveCommit, oidc_token: oidcToken});
  const id = deployment.id || deployment.status_url?.split('/').pop() || archiveCommit;
  core.info(`Deploying documentation archive ${archiveCommit}, artifact ${artifact}`);
  if (deployment.page_url) core.setOutput('page_url', deployment.page_url);
  const deadline = now() + timeoutMs;
  let errors = 0;
  const failure = new Set(['deployment_failed', 'deployment_perms_error', 'deployment_content_failed',
    'deployment_cancelled', 'deployment_lost']);
  while (now() < deadline) {
    await sleep(Math.min(5000, deadline - now()));
    let status;
    try {
      ({data: status} = await github.request('GET /repos/{owner}/{repo}/pages/deployments/{deploymentId}',
        {...repository, deploymentId: id}));
      errors = 0;
    } catch (error) {
      if ((error.status === 404 || error.status >= 500) && ++errors <= 3) continue;
      throw error;
    }
    if (status.status === 'succeed') {
      core.info('Pages reported success; the following step verifies live content.');
      return;
    }
    if (failure.has(status.status)) throw new Error(`Pages deployment failed: ${status.status}`);
  }
  try {
    await github.request('POST /repos/{owner}/{repo}/pages/deployments/{deploymentId}/cancel',
      {...repository, deploymentId: id});
  } catch (_) { /* Preserve the timeout as the primary error. */ }
  throw new Error('Pages deployment timed out');
};
