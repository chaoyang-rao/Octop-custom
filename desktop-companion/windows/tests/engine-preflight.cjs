const path = require("node:path");
const fs = require("node:fs/promises");
const assert = require("node:assert/strict");
const { Engine, health } = require("../engine.cjs");
(async () => {
  const resources = path.resolve(process.argv[2]),
    home = path.resolve(process.argv[3]);
  const engine = new Engine(resources, home, (value) =>
    process.stderr.write(value),
  );
  try {
    const origin = await engine.start((value) => console.log(value));
    const h = await health(origin);
    assert.equal(h.instance, engine.instance);
    assert.equal(h.companion, true);
    const response = await fetch(origin + "/api/auth/me");
    assert.equal(response.status, 401);
    const landing = await fetch(origin + "/login");
    assert.equal(landing.status, 200);
    const manifest = await fetch(origin + "/api/companion/artwork");
    assert.equal(manifest.status, 401);
    console.log(
      JSON.stringify({
        engine_started: true,
        instance_verified: true,
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
