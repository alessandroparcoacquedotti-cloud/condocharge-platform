import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig((configEnv) => {
  const isPreview = process.argv.includes("preview");
  const enableLocalProxy = configEnv.command === "serve" && !isPreview;

  return {
    plugins: [react()],
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
  };
});
