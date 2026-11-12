import type { NextConfig } from "next";

// GitHub Pages serves a static export under /lawg (set by the Pages workflow); docker compose keeps `next start`.
const basePath = process.env.PAGES_BASE_PATH;

const nextConfig: NextConfig = {
  reactStrictMode: true,
  ...(basePath !== undefined && { output: "export", basePath }),
};

export default nextConfig;

