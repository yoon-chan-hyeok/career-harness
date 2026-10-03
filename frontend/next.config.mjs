let backend = process.env.BACKEND_URL || "http://127.0.0.1:8000";
if (process.env.VERCEL === "1") {
  try {
    const origin = new URL(process.env.BACKEND_URL || "");
    if (
      origin.protocol !== "https:" ||
      !origin.hostname ||
      origin.username || origin.password || origin.search || origin.hash ||
      origin.pathname !== "/"
    ) throw new Error();
    backend = origin.origin;
  } catch {
    // Configuration errors must not echo a URL that could contain a credential.
    throw new Error("Vercel BACKEND_URL must be an explicit HTTPS origin without credentials, path, query or fragment.");
  }
}

const config = {
  output: "standalone",
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${backend}/api/:path*`,
      },
    ];
  },
};
export default config;
