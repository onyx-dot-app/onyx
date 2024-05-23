// Get Danswer Web Version
const { version: package_version } = require("./package.json"); // version from package.json
const env_version = process.env.DANSWER_VERSION; // version from env variable
// Use env version if set & valid, otherwise default to package version
const version = env_version || package_version;

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  swcMinify: true,
  rewrites: async () => {
    // In production, something else (nginx in the one box setup) should take
    // care of this rewrite. TODO (chris): better support setups where
    // web_server and api_server are on different machines.
    if (process.env.NODE_ENV === "production") return [];

    return [
      {
        source: "/api/:path*",
        destination: "http://127.0.0.1:8080/:path*", // Proxy to Backend
      },
    ];
  },
  redirects: async () => {
    // In production, something else (nginx in the one box setup) should take
    // care of this redirect. TODO (chris): better support setups where
    // web_server and api_server are on different machines.
    const defaultRedirects = [];

    if (process.env.NODE_ENV === "production") return defaultRedirects;

    return defaultRedirects.concat([
      {
        source: "/api/chat/send-message:params*",
        destination: "http://127.0.0.1:8080/chat/send-message:params*", // Proxy to Backend
        permanent: true,
      },
      {
        source: "/api/query/stream-answer-with-quote:params*",
        destination:
          "http://127.0.0.1:8080/query/stream-answer-with-quote:params*", // Proxy to Backend
        permanent: true,
      },
      {
        source: "/api/query/stream-query-validation:params*",
        destination:
          "http://127.0.0.1:8080/query/stream-query-validation:params*", // Proxy to Backend
        permanent: true,
      },
    ]);
  },
  publicRuntimeConfig: {
    version,
  },
};

module.exports = nextConfig;
