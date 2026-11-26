"use strict";
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const path = require("node:path");
const os = require("node:os");
const { CompanionUpdater, validId } = require("../updater.cjs");
test("native update handoffs reject paths and other product installations before invoking a helper", async (t) => {
  const home = await fs.mkdtemp(path.join(os.tmpdir(), "dora-update-"));
  t.after(() => fs.rm(home, { recursive: true, force: true }));
  const app = path.join(home, "application"),
    resources = path.join(app, "resources"),
    id = "a".repeat(32);
  const calls = [];
  const updater = new CompanionUpdater(resources, home, app, async (...args) =>
    calls.push(args),
  );
  for (const value of [
    "../other",
    "A".repeat(32),
    "a".repeat(31),
    "a\n".repeat(16),
  ])
    assert.equal(validId(value), false);
  assert.throws(() => updater.directory("../other"));
  const directory = updater.directory(id);
  await fs.mkdir(directory, { recursive: true });
  const job = {
    id,
    product: "octop-companion",
    app_root: app,
    data_root: path.join(home, "Data"),
    phase: "applying",
  };
  await fs.writeFile(
    path.join(directory, "job.json"),
    JSON.stringify({ ...job, product: "octop-desktop" }),
  );
  await assert.rejects(updater.start(id, 1234), /当前桌宠/);
  await fs.writeFile(
    path.join(directory, "job.json"),
    JSON.stringify({ ...job, app_root: path.join(home, "other") }),
  );
  await assert.rejects(updater.start(id, 1234), /当前桌宠/);
  assert.equal(calls.length, 0);
  await fs.writeFile(path.join(directory, "job.json"), JSON.stringify(job));
  assert.equal((await updater.read(id)).id, id);
  await updater.validate(id, "--validate");
  assert.deepEqual(calls[0][1], [
    "--home",
    path.join(home, "Data"),
    "--job",
    id,
    "--product",
    "octop-companion",
    "--validate",
  ]);
});
