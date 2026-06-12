/** @type {import('next').NextConfig} */
const nextConfig = {
    output: "standalone",
    reactStrictMode: true,
    poweredByHeader: false,

    // Proxy API calls in dev mode
    async rewrites() {
        return [
            {
                source: "/api/:path*",
                destination: `${process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000"}/api/:path*`,
            },
        ];
    },

    // Environment variables exposed to the browser
    env: {
        NEXT_PUBLIC_API_BASE_URL: process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000",
        NEXT_PUBLIC_WS_URL: process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000/ws",
    },
};

module.exports = nextConfig;