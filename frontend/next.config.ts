import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  async rewrites() {
    return [
      {
        source: "/api/backend/:path*",
        destination: "http://localhost:8000/:path*", // Updated port
      },
      {
        source: "/auth/callback",
        destination: "/api/backend/auth/callback",
      },
    ];
  },
  env: {
    NEXT_PUBLIC_GITHUB_CLIENT_ID: "Iv23liUpW8R79TphqMWl",
    NEXT_PUBLIC_API_URL: "http://localhost:8000", // Corrected: base URL for backend
  },
};

export default nextConfig;
