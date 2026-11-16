import { defineConfig } from "vite";

export default defineConfig({
  root: "web",
  base: "./",
  build: {
    outDir: "../dist/web",
    emptyOutDir: true,
    cssCodeSplit: false,
    rollupOptions: { output: { format: "iife", inlineDynamicImports: true } },
  },
  plugins: [
    {
      name: "wkwebview-classic-entry",
      generateBundle: {
        order: "post",
        handler(_options, bundle) {
          for (const value of Object.values(bundle)) {
            if (
              value.type === "asset" &&
              value.fileName.endsWith(".html") &&
              typeof value.source === "string"
            ) {
              value.source = value.source
                .replace(/type="module"/g, "defer")
                .replace(/\s+crossorigin(?:="[^"]*")?/g, "");
            }
          }
        },
      },
    },
  ],
  // A single classic script works from WKWebView's restricted local file origin.
  // No local HTTP server, copied cookies, or weakened file-access preferences.
  // Vite still handles the source as modules during development.
});
