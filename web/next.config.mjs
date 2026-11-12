const api = process.env.API_URL ?? "http://127.0.0.1:8000";

export default {
  poweredByHeader: false,
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${api}/api/:path*` }];
  },
};
