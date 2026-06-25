import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { VitePWA } from "vite-plugin-pwa";

const themeColor = "#1a2a52";
const backgroundColor = "#f4f7fb";

export default defineConfig((configEnv) => {
  const isPreview = process.argv.includes("preview");
  const enableLocalProxy = configEnv.command === "serve" && !isPreview;

  return {
    plugins: [
      react(),
      VitePWA({
        strategies: "injectManifest",
        srcDir: "src",
        filename: "sw.ts",
        registerType: "autoUpdate",
        injectRegister: "auto",
        includeAssets: [
          "apple-touch-icon.png",
          "maskable-icon-512x512.png",
          "pwa-192x192.png",
          "pwa-512x512.png",
        ],
        manifest: {
          name: "CondoCharge",
          short_name: "CondoCharge",
          description: "Gestione ricariche condominiali",
          start_url: "/",
          scope: "/",
          display: "standalone",
          orientation: "portrait",
          theme_color: themeColor,
          background_color: backgroundColor,
          icons: [
            {
              src: "pwa-192x192.png",
              sizes: "192x192",
              type: "image/png",
            },
            {
              src: "pwa-512x512.png",
              sizes: "512x512",
              type: "image/png",
            },
            {
              src: "maskable-icon-512x512.png",
              sizes: "512x512",
              type: "image/png",
              purpose: "any maskable",
            },
          ],
        },
        injectManifest: {
          globPatterns: ["**/*.{css,html,ico,js,png,svg,webp}"],
        },
      }),
    ],
    server: {
      host: true,
      port: 5173,
      ...(enableLocalProxy
        ? {
            proxy: {
              "/api": {
                target: "http://127.0.0.1:8001",
                changeOrigin: true,
              },
            },
          }
        : {}),
    },
    preview: {
      host: true,
      allowedHosts: [".up.railway.app"],
    },
    test: {
      environment: "jsdom",
      globals: true,
      setupFiles: "./src/test/setup.ts",
    },
  };
});
