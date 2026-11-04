/** @type {import('next').NextConfig} */
const nextConfig = {
  agentRules: false,
  // The dev server otherwise blocks the browser when the page is opened as 127.0.0.1.
  allowedDevOrigins: ["127.0.0.1"],
  experimental: {
    serverActions: {
      bodySizeLimit: "10mb",
    },
  },
};

export default nextConfig;
