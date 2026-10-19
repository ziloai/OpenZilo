const test = require('node:test');
const assert = require('node:assert/strict');
const deploy = require('../.github/scripts/deploy-docs.cjs');

function fixture(statuses = ['succeed']) {
  const calls = [];
  let clock = 0;
  const outputs = {};
  const options = {
    archiveCommit: 'b'.repeat(40), artifactId: '123', timeoutMs: 20000,
    context: {repo: {owner: 'example', repo: 'docs'}, sha: 'a'.repeat(40)},
    core: {getIDToken: async () => 'synthetic-oidc', setSecret: () => {},
      info: () => {}, setOutput: (name, value) => { outputs[name] = value; }},
    now: () => clock, sleep: async ms => { clock += ms; },
    github: {request: async (route, body) => {
      calls.push({route, body});
      if (route.startsWith('GET /repos/{owner}/{repo}/git/')) return {data: {}};
      if (route === 'POST /repos/{owner}/{repo}/pages/deployments') {
        return {data: {id: 'deployment-id', page_url: 'https://example.github.io/docs/'}};
      }
      if (route.endsWith('/cancel')) return {data: {}};
      const status = statuses.length > 1 ? statuses.shift() : statuses[0];
      if (status instanceof Error) throw status;
      return {data: {status}};
    }}
  };
  return {options, calls, outputs};
}

test('same SDK SHA with different archives uses different deployment IDs', async () => {
  const first = fixture(), second = fixture();
  second.options.archiveCommit = 'c'.repeat(40);
  await deploy(first.options);
  await deploy(second.options);
  const payload = f => f.calls.find(c => c.route === 'POST /repos/{owner}/{repo}/pages/deployments').body;
  assert.equal(payload(first).pages_build_version, 'b'.repeat(40));
  assert.equal(payload(second).pages_build_version, 'c'.repeat(40));
  assert.notEqual(payload(first).pages_build_version, first.options.context.sha);
  assert.equal(payload(first).artifact_id, 123);
  assert.equal(first.calls[0].body.commit_sha, 'b'.repeat(40));
  assert.equal(first.outputs.page_url, 'https://example.github.io/docs/');
});

test('bad identity or missing artifact cannot initiate deployment', async () => {
  for (const change of [{archiveCommit: 'timestamp'}, {artifactId: ''}, {artifactId: 'NaN'}, {artifactId: '0'}]) {
    const f = fixture();
    await assert.rejects(deploy({...f.options, ...change}), /Invalid/);
    assert.equal(f.calls.length, 0);
  }
});

test('missing pushed archive cannot initiate deployment', async () => {
  const f = fixture();
  f.options.github.request = async () => { throw Object.assign(new Error('not found'), {status: 404}); };
  await assert.rejects(deploy(f.options), /not found/);
});

test('polls progress and transient status failures', async () => {
  const error = Object.assign(new Error('temporarily unavailable'), {status: 503});
  const f = fixture(['queued', error, 'succeed']);
  await deploy(f.options);
  assert.equal(f.calls.filter(c => c.route.endsWith('/{deploymentId}')).length, 3);
});

test('terminal failure is not success', async () => {
  const f = fixture(['deployment_content_failed']);
  await assert.rejects(deploy(f.options), /deployment_content_failed/);
});

test('authorization and repeated status failures are not hidden', async () => {
  for (const code of [403, 503]) {
    const f = fixture([Object.assign(new Error('HTTP failure'), {status: code})]);
    f.options.timeoutMs = 30000;
    await assert.rejects(deploy(f.options), /HTTP failure/);
  }
});

test('timeout cancels the deployment', async () => {
  const f = fixture(['queued']);
  await assert.rejects(deploy(f.options), /timed out/);
  assert.equal(f.calls.at(-1).route, 'POST /repos/{owner}/{repo}/pages/deployments/{deploymentId}/cancel');
});
