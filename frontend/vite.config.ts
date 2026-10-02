/// <reference types="vitest/config" />
import path from "node:path";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";
import { VitePWA } from "vite-plugin-pwa";

const ROOT = path.resolve(import.meta.dirname, "..");

export default defineConfig(({ mode }) => {
  // One `.env` at the repository root serves backend and frontend.
  const env = loadEnv(mode, ROOT, "");
  for (const [name, value] of Object.entries(env)) {
    if (name.startsWith("VITE_") && (
      /(?:API_?KEY|(?:^|_)KEY(?:_|$)|SECRET|TOKEN|PASSWORD)/i.test(name)
      || /\bsk-[A-Za-z0-9_-]{20,}/.test(value)
      || Boolean(env.OPENAI_API_KEY && value.includes(env.OPENAI_API_KEY))
    )) {
      throw new Error(`Server credentials must not be exposed through ${name}`);
    }
  }
  const apiProxyTarget = env.VITE_DEV_API_PROXY_TARGET || "http://127.0.0.1:8100";
  const demoMode = /^(true|1)$/i.test(process.env.DEMO_MODE ?? env.DEMO_MODE ?? env.VITE_DEMO_MODE ?? "false");

  return {
    envDir: ROOT,
    define: { "import.meta.env.VITE_DEMO_MODE": JSON.stringify(demoMode ? "true" : "false") },
    resolve: { alias: { "@": path.resolve(import.meta.dirname, "src") } },
    plugins: [
      react(),
      tailwindcss(),
      VitePWA({
        registerType: "prompt",
        injectRegister: false,
        includeAssets: ["favicon.svg", "favicon.ico", "apple-touch-icon-180x180.png"],
        manifest: {
          id: "/",
          name: "ADAPT: your move to Abu Dhabi",
          short_name: "ADAPT",
          description:
            "Plan your move to Abu Dhabi: company setup, residency, housing, family and community, with sources and clear next steps.",
          lang: "en",
          dir: "ltr",
          start_url: demoMode ? "/demo/founder-arrival" : "/",
          scope: "/",
          display: "standalone",
          display_override: ["standalone", "minimal-ui"],
          orientation: "any",
          // Android builds its launch splash from these: limestone canvas, navy mark.
          theme_color: "#0F1C2E",
          background_color: "#F5F4F0",
          categories: ["productivity", "lifestyle", "travel"],
          icons: [
            { src: "pwa-64x64.png", sizes: "64x64", type: "image/png" },
            { src: "pwa-192x192.png", sizes: "192x192", type: "image/png" },
            { src: "pwa-512x512.png", sizes: "512x512", type: "image/png" },
            { src: "maskable-icon-512x512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
          ],
          shortcuts: [
            { name: "ADAPT Interpreter", short_name: "Interpreter", url: "/interpreter?source=en&target=ar", icons: [{ src: "pwa-192x192.png", sizes: "192x192" }] },
            { name: "Your next step", short_name: "Home", url: "/home", icons: [{ src: "pwa-192x192.png", sizes: "192x192" }] },
            { name: "Journey map", short_name: "Journey", url: "/journey", icons: [{ src: "pwa-192x192.png", sizes: "192x192" }] },
            { name: "Scan a document", short_name: "Scan", url: "/documents?upload=passport", icons: [{ src: "pwa-192x192.png", sizes: "192x192" }] },
            { name: "Ask ADAPT", short_name: "Assistant", url: "/assistant", icons: [{ src: "pwa-192x192.png", sizes: "192x192" }] },
          ],
        },
        workbox: {
          // Offline application shell only. API responses and uploaded documents are
          // private: they are never precached or runtime-cached.
          globPatterns: ["**/*.{js,css,html,svg,png,ico,woff2,webmanifest}"],
          // iOS reads launch images straight from the network; don't precache ~80 of them.
          globIgnores: ["**/apple-splash-*.png", "**/uploads/**", "**/private/**", "**/demo-specimens/**"],
          navigateFallback: "/index.html",
          navigateFallbackDenylist: [/^\/api(?:\/|$)/, /^\/uploads(?:\/|$)/, /^\/private(?:\/|$)/],
          runtimeCaching: [
            {
              // Includes signed document content URLs: always from the network, never stored.
              urlPattern: ({ url }) => /^\/(api|uploads|private)(\/|$)/.test(url.pathname),
              handler: "NetworkOnly",
            },
          ],
          cleanupOutdatedCaches: true,
          clientsClaim: false,
          maximumFileSizeToCacheInBytes: 3 * 1024 * 1024,
        },
        devOptions: { enabled: false },
      }),
    ],
    server: {
      port: 5180,
      host: "127.0.0.1",
      hmr: { overlay: !demoMode },
      proxy: {
        "/api": { target: apiProxyTarget, changeOrigin: false },
      },
    },
    preview: { port: 5181, host: "127.0.0.1" },
    build: {
      target: "es2022",
      sourcemap: !demoMode,
      // Never inline fonts as data: URIs — the CSP only allows same-origin font files.
      assetsInlineLimit: (file: string) => (/\.woff2?$/.test(file) ? false : undefined),
    },
    test: {
      environment: "node",
      include: ["src/**/*.test.ts"],
      env: { VITE_DATA_MODE: "auto" },
    },
  };
});
