import { reactRouter } from "@react-router/dev/vite";
import { defineConfig, loadEnv } from "vite";
export default defineConfig(({ mode }) => {
  // React Router loads SSR process.env later; the API proxy needs it here.
  const env = loadEnv(mode, process.cwd(), "API_ORIGIN");
  return {
    plugins: [reactRouter()],
    server: {
      proxy: {
        "/api": {
          target: env.API_ORIGIN ?? "http://127.0.0.1:8000",
          changeOrigin: false,
        },
      },
    },
  };
});
