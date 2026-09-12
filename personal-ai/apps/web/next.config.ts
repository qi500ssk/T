import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Next.js 默认代理超时为 30 秒，文档入库和模型首字等待可能超过它。
  experimental: { proxyTimeout: 300_000 },
  async rewrites() {
    return [{
      source: "/api/:path*",
      destination: `${process.env.API_INTERNAL_URL || "http://127.0.0.1:8787"}/api/:path*`,
    }];
  },
};

export default nextConfig;
