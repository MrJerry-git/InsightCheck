import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  experimental: { proxyTimeout: 300_000, proxyClientMaxBodySize: "12mb" },
  async rewrites() {
    return [{
      source: "/api/prevention/:path*",
      destination: `${process.env.INSIGHTCHECK_BACKEND_URL ?? "http://127.0.0.1:8000"}/api/v1/prevention/:path*`,
    }];
  },
};

export default nextConfig;
