"use strict";
const fs = require("node:fs");
const fsp = fs.promises;
const path = require("node:path");
const { pipeline } = require("node:stream/promises");
const { createHash } = require("node:crypto");
const yauzl = require("yauzl");
function safeEntry(name) {
  if (
    typeof name !== "string" ||
    !name ||
    name.includes("\\") ||
    name.startsWith("/") ||
    /[\x00-\x1f:]/.test(name)
  )
    throw new Error("组件包含不安全的路径。");
  const parts = name.replace(/\/$/, "").split("/");
  if (
    parts.some(
      (p) =>
        !p ||
        p === "." ||
        p === ".." ||
        /[. ]$/.test(p) ||
        /^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)/i.test(p),
    )
  )
    throw new Error("组件包含不安全的路径。");
  return parts;
}
async function digest(file) {
  const hash = createHash("sha256");
  for await (const chunk of fs.createReadStream(file)) hash.update(chunk);
  return hash.digest("hex");
}
async function extract(
  file,
  destination,
  { root, maxSize = 3 * 1024 ** 3 } = {},
) {
  await fsp.mkdir(destination, { recursive: true });
  const zip = await new Promise((resolve, reject) =>
    yauzl.open(
      file,
      { lazyEntries: true, strictFileNames: true, validateEntrySizes: true },
      (err, value) => (err ? reject(err) : resolve(value)),
    ),
  );
  let total = 0,
    count = 0;
  const seen = new Set();
  await new Promise((resolve, reject) => {
    const fail = (e) => {
      zip.close();
      reject(e);
    };
    zip.on("error", fail);
    zip.on("end", resolve);
    zip.on("entry", (entry) => {
      void (async () => {
        const parts = safeEntry(entry.fileName),
          mode = (entry.externalFileAttributes >>> 16) & 0xf000;
        if (
          (root && parts[0] !== root) ||
          mode === 0xa000 ||
          ++count > 100000 ||
          (total += entry.uncompressedSize) > maxSize
        )
          throw new Error("组件目录或大小不符合发布要求。");
        const key = parts.join("/").toLowerCase();
        if (seen.has(key)) throw new Error("组件包含重复的文件路径。");
        seen.add(key);
        const target = path.join(destination, ...parts);
        if (entry.fileName.endsWith("/"))
          await fsp.mkdir(target, { recursive: true });
        else {
          await fsp.mkdir(path.dirname(target), { recursive: true });
          const input = await new Promise((res, rej) =>
            zip.openReadStream(entry, (e, s) => (e ? rej(e) : res(s))),
          );
          await pipeline(input, fs.createWriteStream(target, { flags: "wx" }));
        }
        zip.readEntry();
      })().catch(fail);
    });
    zip.readEntry();
  });
}
module.exports = { safeEntry, extract, digest };
