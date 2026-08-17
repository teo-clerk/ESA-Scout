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

  // The dashboard reads public/data/opportunities.json from disk at request
  // time, so it must be traced into the serverless bundle.
  outputFileTracingIncludes: {
    "/": ["./public/data/**"],
    "/api/opportunities": ["./public/data/**"],
  },
};

export default nextConfig;
