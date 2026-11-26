import { defineConfig } from "vite";
import { fileURLToPath } from "node:url";

export default defineConfig({
  root: fileURLToPath(new URL(".", import.meta.url)),
  base: "/client-update-center/",
  esbuild: { jsx: "automatic" },
  build: {
    outDir: fileURLToPath(
      new URL(
        "../../desktop-companion/build/client-update-center",
        import.meta.url,
      ),
    ),
    emptyOutDir: true,
    target: "es2022",
  },
});
