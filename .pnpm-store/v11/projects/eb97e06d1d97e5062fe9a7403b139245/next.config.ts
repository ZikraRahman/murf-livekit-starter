import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  turbopack: {
    // Keep Next's workspace detection inside this frontend package.
    root: __dirname,
  },
  eslint: {
    // These warnings come from upstream LiveKit/AI UI components, not our code.
    ignoreDuringBuilds: true,
  },
};

export default nextConfig;
