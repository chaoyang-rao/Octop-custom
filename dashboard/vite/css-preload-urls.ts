import type { Plugin } from "vite";

/** Classify the resource pathname, retaining query/fragment cache versions. */
export function cssPreloadUrls(): Plugin {
  return {
    name: "octop-css-preload-urls",
    apply: "build",
    enforce: "post",
    transform(code, id) {
      if (id !== "\0vite/preload-helper.js") return;
      const next = code.replace(
        /\bdep\.endsWith\((["'])\.css\1\)/g,
        'dep.split(/[?#]/, 1)[0].endsWith(".css")',
      );
      if (next === code) {
        this.error(
          "Review the CSS preload URL adapter after the Vite helper changed.",
        );
      }
      return { code: next, map: null };
    },
  };
}
