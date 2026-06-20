import path from "path";

/** @type {import('next').NextConfig} */
const nextConfig = {
  webpack(config) {
    // Explicitly wire @/ → src/ so the alias works on all build environments
    // (tsconfig paths alone can be unreliable in Docker/CI on Linux).
    config.resolve.alias["@"] = path.join(process.cwd(), "src");
    return config;
  },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination:
          (process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000") +
          "/api/:path*",
      },
    ];
  },
};

export default nextConfig;
