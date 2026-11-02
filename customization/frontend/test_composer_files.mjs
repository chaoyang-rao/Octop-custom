import { readFileSync } from "node:fs";
import { collectSentLinks } from "../packages/octop/dashboard/assets/composer-files.js";

const failures = [];
const check = (name, condition) => {
  if (!condition) failures.push(name);
};

const links = collectSentLinks([
  { role: "user", content: "看下 https://example.com/a，再 https://example.com/a" },
  { role: "assistant", content: "https://ignored.example/x" },
  { role: "user", content: [{ type: "text", text: "还有 https://www.python.org/ 。" }] },
]);
check("dedupe", links.filter((url) => url === "https://example.com/a").length === 1);
check("newest-first", links[0] === "https://www.python.org/");
check("ignores assistant", !links.some((url) => url.includes("ignored.example")));
check("strips punctuation", links.includes("https://www.python.org/"));

const asset = readFileSync(
  new URL("../packages/octop/dashboard/assets/composer-files.js", import.meta.url),
  "utf8",
);
check("lists files and links", asset.includes('"chat.files.links"'));
check("uses page titles", asset.includes("link.title || hostOf(link.url)"));

if (failures.length) {
  console.error("FAIL", failures);
  process.exit(1);
}
console.log("PASS sent links extraction and links-with-titles panel");
