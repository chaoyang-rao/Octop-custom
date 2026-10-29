/* Local, read-only fixture: node customization/frontend/compact-chat.fixture.mjs */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import {
  ORIGINAL_COMPOSER_MINIMUM,
  COMPACT_COMPOSER_MINIMUM,
  patchCompactChatSource,
} from "./compact-chat-patch.mjs";

const require = createRequire(new URL("../../dashboard/package.json", import.meta.url));
const postcss = require("postcss");
const asset = (name) => new URL("../packages/octop/dashboard/assets/" + name, import.meta.url);
const chatChunk = readFileSync(asset("index.G9_xhF8C.avatars-v4.js"), "utf8");
const originalCss = readFileSync(asset("index.Ds_DN6_-.avatars-v4.css"), "utf8");
const markdownCss = readFileSync(asset("index.BsfH4C6q.avatars-v4.css"), "utf8");
const compactCss = readFileSync(asset("compact-chat.css"), "utf8");
const compactTree = postcss.parse(compactCss);
const sourceTree = postcss.parse(originalCss + "\n" + markdownCss);
const combinedTree = postcss.parse(originalCss + "\n" + markdownCss + "\n" + compactCss);

const patchedChunk = patchCompactChatSource(chatChunk);
assert.equal(patchedChunk.includes(ORIGINAL_COMPOSER_MINIMUM), false);
assert.equal(patchedChunk.split(COMPACT_COMPOSER_MINIMUM).length - 1, 1);
assert.equal(
  patchedChunk.replace(COMPACT_COMPOSER_MINIMUM, ORIGINAL_COMPOSER_MINIMUM),
  chatChunk,
  "The pure patch must preserve every other byte, including autosize and event handlers",
);
assert.ok(patchedChunk.includes("Math.max(Math.min(h,160),MIN_TEXTAREA_HEIGHT)"));
assert.throws(() => patchCompactChatSource(""), /found 0/);
assert.throws(() => patchCompactChatSource(chatChunk + ORIGINAL_COMPOSER_MINIMUM), /found 2/);
assert.throws(() => patchCompactChatSource(patchedChunk), /found 0/);

const cls = {
  page: "index-module__chatPage__lB-np",
  wrapper: "index-module__inputWrapper__QeKz7",
  textarea: "index-module__textarea__lUFuW",
  row: "index-module__actionsRow__-BkcX",
  secondary: "index-module__secondaryActions__lMtdc",
  secondaryBtn: "index-module__secondaryBtn__RjZzE",
  send: "index-module__sendBtn__jFtPt",
  ring: "index-module__contextRingSvg__1kIs2",
  ringLabel: "index-module__contextRingLabel__tpB1V",
  user: "index-module__userText__70Ung",
  assistant: "index-module__assistantText__t-CQA",
  markdown: "index-module__markdownBody__-OevX",
};

/* Resolve the real source declarations for these simple class-only fixtures. */
function computed(tree, target, width, ancestorClasses = []) {
  const classes = new Set([...ancestorClasses, target]);
  const result = {};
  const priorities = {};
  tree.walkRules((rule) => {
    for (let parent = rule.parent; parent && parent.type !== "root"; parent = parent.parent) {
      if (parent.type !== "atrule") continue;
      if (parent.name === "container") return; // wide desktop fixture, no narrow dock
      if (parent.name === "media") {
        for (const match of parent.params.matchAll(/(max|min)-width\s*:\s*(\d+)px/g)) {
          if (match[1] === "max" && width > +match[2]) return;
          if (match[1] === "min" && width < +match[2]) return;
        }
        if (parent.params.includes("prefers-reduced-motion")) return;
      }
    }
    for (const selector of rule.selectors) {
      if (selector.includes(":")) continue;
      const required = [...selector.matchAll(/\.([\w-]+)/g)].map((match) => match[1]);
      if (!selector.trim().endsWith(`.${target}`) || required.some((name) => !classes.has(name))) continue;
      rule.walkDecls((decl) => {
        const priority = required.length + (decl.important ? 1000 : 0);
        const assign = (key, value) => {
          if ((priorities[key] ?? -1) > priority) return;
          result[key] = value;
          priorities[key] = priority;
        };
        assign(decl.prop, decl.value);
        if (decl.prop === "padding" || decl.prop === "margin") {
          const values = decl.value.split(/\s+/);
          const [top, right = top, bottom = top, left = right] = values;
          for (const [side, value] of Object.entries({ top, right, bottom, left })) {
            assign(`${decl.prop}-${side}`, value);
          }
        }
      });
    }
  });
  return result;
}

const ancestors = [cls.page, cls.wrapper];
const before = (target, width = 1440) => computed(sourceTree, target, width, ancestors);
const after = (target, width = 1440, extra = []) => computed(combinedTree, target, width, [...ancestors, ...extra]);
const numbers = {
  userFont: [parseFloat(before(cls.user)["font-size"]), parseFloat(after(cls.user)["font-size"])],
  assistantFont: [parseFloat(before(cls.assistant)["font-size"]), parseFloat(after(cls.assistant)["font-size"])],
  markdownFont: [parseFloat(before(cls.markdown)["font-size"]), parseFloat(after(cls.markdown)["font-size"])],
  mobileMarkdownFont: [parseFloat(before(cls.markdown, 375)["font-size"]), parseFloat(after(cls.markdown, 375)["font-size"])],
  textareaFont: [parseFloat(before(cls.textarea)["font-size"]), parseFloat(after(cls.textarea)["font-size"])],
  desktopMinimum: [78, 39],
  mobileMinimum: [42, 24],
};
assert.deepEqual(numbers.userFont, [14, 13]);
assert.deepEqual(numbers.assistantFont, [15, 13]);
assert.deepEqual(numbers.markdownFont, [15, 13]);
assert.deepEqual(numbers.mobileMarkdownFont, [16, 13]);
assert.deepEqual(numbers.textareaFont, [14, 13]);
assert.equal(after(cls.textarea)["min-height"], "39px");
assert.equal(after(cls.textarea, 375)["min-height"], "24px");
assert.equal(after(cls.textarea)["max-height"], "160px");
assert.equal(after(cls.textarea)["overflow-y"], "auto");
assert.equal(after(cls.textarea)["box-sizing"], "border-box");
assert.equal(after(cls.secondaryBtn, 1440, [cls.row]).height, "24px");
assert.equal(after(cls.send, 1440, [cls.row]).height, "24px");
assert.equal(after(cls.ring, 1440, [cls.row]).height, "16px");
assert.equal(after(cls.ringLabel, 1440, [cls.row])["font-size"], "9px");

const glyphs = {};
compactTree.walkRules((rule) => {
  if (rule.selector.includes("svg")) {
    for (const selector of rule.selectors) {
      assert.ok(selector.startsWith(`.${cls.row} `), "SVG overrides must stay inside the composer toolbar");
    }
  }
  const width = rule.selector.match(/svg\[width="(\d+)"\]/);
  if (width) {
    const declarations = Object.fromEntries(rule.nodes.filter((node) => node.type === "decl").map((node) => [node.prop, node.value]));
    const original = Number(width[1]);
    assert.equal(parseFloat(declarations.width), original / 2);
    assert.equal(parseFloat(declarations.height), original / 2);
    glyphs[original] = original / 2;
  }
  if (rule.selector.includes(cls.wrapper)) {
    for (const declaration of rule.nodes.filter((node) => node.type === "decl")) {
      assert.ok(!["height", "max-height", "overflow", "overflow-y"].includes(declaration.prop), "Attachment and queue previews must remain unconstrained");
    }
  }
});
assert.deepEqual(glyphs, { 12: 6, 14: 7, 15: 7.5, 16: 8, 18: 9 });

const wrapper = after(cls.wrapper);
const row = after(cls.row);
const compactToolbarHeight = 24 + parseFloat(row["padding-top"]) + 1 + parseFloat(row["margin-top"]);
const compactWrapperChrome = parseFloat(wrapper["padding-top"]) + parseFloat(wrapper["padding-bottom"]) + 2;
const geometry = {
  /* Unwrapped craft-mode fixture: no attachments, queues, or mode reminder. */
  desktop: 39 + compactToolbarHeight + compactWrapperChrome,
  mobile: 24 + compactToolbarHeight + compactWrapperChrome,
};
assert.equal(geometry.desktop, 80);
assert.equal(geometry.mobile, 65);
assert.ok(geometry.desktop / 157 < 0.52, "Compact empty desktop box is about half the original border-box estimate");

console.log(JSON.stringify({
  ok: true,
  source: "Source CSS cascade and pure patch fixture; real UI measurement remains separate",
  beforeAfterPx: numbers,
  toolbarGlyphBeforeAfterPx: glyphs,
  compactEmptyCraftBoxCalculatedPx: geometry,
  preserved: ["160px autosize cap", "all other chat source bytes", "preview natural height", "context label 9px", "existing theme colors", "avatar rules"],
}, null, 2));
