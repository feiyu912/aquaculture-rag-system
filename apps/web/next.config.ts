import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // The floating dev badge overlaps the mobile tab bar during UI review.
  devIndicators: false,
  // The dev server is reached through 127.0.0.1 in the review harness.
  allowedDevOrigins: ["127.0.0.1", "localhost"],
  // pdf.js ships ESM workers that Next must not try to bundle on the server.
  experimental: {
    optimizePackageImports: ["lucide-react", "recharts"],
  },
  webpack: (config, { isServer }) => {
    if (!isServer) {
      config.resolve.fallback = { ...config.resolve.fallback, fs: false, path: false };
    }
    return config;
  },
};

export default nextConfig;
