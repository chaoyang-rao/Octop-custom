const path = require("node:path");
const fs = require("node:fs");
const assert = require("node:assert/strict");
const { Engine, health } = require("../engine.cjs");
(async () => {
  const resources = path.resolve(process.argv[2]),
    home = path.resolve(process.argv[3]);
  fs.mkdirSync(home, { recursive: true });
  const engine = new Engine(resources, home, (value) =>
    fs.appendFileSync(path.join(home, "engine.log"), value),
  );
  try {
    const origin = await engine.start((value) => console.log(value));
    const h = await health(origin);
    assert.equal(h.instance, engine.instance);
    assert.equal(h.companion, true);
    const response = await fetch(origin + "/api/auth/me");
    assert.equal(response.status, 503);
    assert.deepEqual(await response.json(), { setup_required: true });
    const setup = await fetch(origin + "/api/setup/status");
    assert.equal(setup.status, 200);
    const setupState = await setup.json();
    assert.equal(setupState.enterprise_login, true);
    assert.equal(setupState.setup_required, false);
    const landing = await fetch(origin + "/login");
    assert.equal(landing.status, 200);
    const manifest = await fetch(origin + "/api/companion/artwork");
    assert.equal(manifest.status, 503);
    assert.deepEqual(await manifest.json(), { setup_required: true });
    console.log(
      JSON.stringify({
        engine_started: true,
        instance_verified: true,
        enterprise_login_without_setup_wizard: true,
        login_page: landing.status,
        anonymous_artwork: manifest.status,
        data_home: path.join(home, "Data"),
      }),
    );
  } finally {
    engine.stop();
  }
})().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
