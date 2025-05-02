import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  async rewrites() {
    return [
      {
        source: "/api/backend/:path*", // Proxy requests from this path on the frontend
        destination: "http://localhost:8000/:path*", // Forward to the backend
      },
    ];
  },
};

export default nextConfig;
