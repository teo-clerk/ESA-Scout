import path from "node:path";
import { fileURLToPath } from "node:url";

const projectRoot = path.dirname(fileURLToPath(import.meta.url));

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,

  // The repository root also contains the Python agent; pin the app root so the
  // bundler does not walk up and try to infer a workspace.
  turbopack: {
    root: projectRoot,
  },

  // Both dashboards read their JSON from public/data at request time, so those
  // files must be traced into each serverless bundle that touches them.
  outputFileTracingIncludes: {
    "/": ["./public/data/**"],
    "/sme": ["./public/data/**"],
    "/api/opportunities": ["./public/data/**"],
    "/api/sme": ["./public/data/**"],
  },
};

export default nextConfig;
