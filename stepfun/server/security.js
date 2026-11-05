import { HttpError } from "./validation.js";

export function requestGuard(port) {
  const allowedPorts = new Set([String(port)]);
  if (process.env.NODE_ENV !== "production") allowedPorts.add("5173");

  function isAllowedUrl(value) {
    try {
      const url = new URL(value.includes("://") ? value : `http://${value}`);
      return (
        url.protocol === "http:" &&
        ["127.0.0.1", "localhost"].includes(url.hostname) &&
        allowedPorts.has(url.port || "80")
      );
    } catch {
      return false;
    }
  }

  return (request, _response, next) => {
    const origin = request.headers.origin;
    const fetchSite = request.headers["sec-fetch-site"];
    const valid =
      isAllowedUrl(request.headers.host || "") &&
      (!origin || isAllowedUrl(origin)) &&
      (!fetchSite || ["same-origin", "same-site", "none"].includes(fetchSite));
    next(valid ? undefined : new HttpError(403, "仅允许本机同源请求"));
  };
}
