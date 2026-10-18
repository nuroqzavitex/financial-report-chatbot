import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // self-contained server bundle for the Docker image (infra/docker/web.Dockerfile)
  output: "standalone",
};

export default nextConfig;
