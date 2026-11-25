"use strict";
const fs = require("node:fs");
const fsp = fs.promises;
const path = require("node:path");
const { pipeline } = require("node:stream/promises");
const { Transform } = require("node:stream");
const { randomUUID } = require("node:crypto");
const policy = require("./security.cjs");
const { digest, extract } = require("./archive.cjs");
async function ensureArtwork(client, home) {
  const metadata = policy.verifyPackage(
    await client.data("/api/companion/artwork"),
  );
  const target = path.join(home, "Artwork", metadata.sha256.slice(0, 16));
  try {
    await fsp.access(path.join(target, ".ready"));
    return path.join(target, "frames");
  } catch {}
  const revision = client.revision;
  const download = await client.request("/api/companion/artwork/file", {
    stream: true,
  });
  if (download.status !== 200) {
    download.response.destroy();
    throw new Error("桌宠形象暂未开放，请联系管理员。");
  }
  const stage = target + "." + randomUUID(),
    archive = stage + ".zip";
  let size = 0;
  try {
    await fsp.mkdir(path.dirname(stage), { recursive: true });
    await pipeline(
      download.response,
      new Transform({
        transform(chunk, _encoding, callback) {
          size += chunk.length;
          callback(
            size > metadata.size
              ? new Error("形象组件大小超出发布记录。")
              : null,
            chunk,
          );
        },
      }),
      fs.createWriteStream(archive, { flags: "wx" }),
    );
    if (size !== metadata.size || (await digest(archive)) !== metadata.sha256)
      throw new Error("桌宠形象校验失败。");
    if (revision !== client.revision) throw new Error("登录状态已经变化。");
    await extract(archive, stage, { root: "frames", maxSize: 512 * 1024 ** 2 });
    await readModel(path.join(stage, "frames"));
    await fsp.writeFile(path.join(stage, ".ready"), metadata.sha256);
    await fsp.rename(stage, target);
    return path.join(target, "frames");
  } finally {
    await fsp.rm(stage, { recursive: true, force: true });
    await fsp.rm(archive, { force: true });
  }
}
async function readModel(directory) {
  const manifest = JSON.parse(
    await fsp.readFile(path.join(directory, "pet.json"), "utf8"),
  );
  if (
    !manifest.animations?.idle ||
    !manifest.registration?.frames ||
    !manifest.peek?.right ||
    !manifest.peek?.bottom
  )
    throw new Error("桌宠动作组件不完整。");
  const names = new Set();
  for (const animation of Object.values(manifest.animations)) {
    for (const name of animation.frames) names.add(name);
    if (animation.baseFrame) names.add(animation.baseFrame);
  }
  for (const peek of Object.values(manifest.peek)) names.add(peek.frame);
  const images = {};
  for (const name of names) {
    if (!/^[a-zA-Z0-9._-]+\.png$/.test(name))
      throw new Error("桌宠图片路径无效。");
    const file = path.join(directory, name),
      stat = await fsp.lstat(file);
    if (!stat.isFile() || stat.isSymbolicLink() || stat.size > 8 * 1024 ** 2)
      throw new Error("桌宠图片无效。");
    images[name] =
      "data:image/png;base64," + (await fsp.readFile(file)).toString("base64");
  }
  return { manifest, images };
}
module.exports = { ensureArtwork, readModel };
