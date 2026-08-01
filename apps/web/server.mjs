import { createReadStream, existsSync, statSync } from "node:fs";
import { createServer } from "node:http";
import { extname, join, normalize } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("./dist/", import.meta.url));
const port = Number(process.env.PORT ?? 3000);
const contentTypes = {
  ".css": "text/css; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
};

createServer((request, response) => {
  if (request.url === "/health") {
    response.writeHead(200, { "Content-Type": "text/plain; charset=utf-8" });
    response.end("healthy");
    return;
  }

  const pathname = new URL(request.url ?? "/", "http://localhost").pathname;
  const relative = normalize(decodeURIComponent(pathname)).replace(
    /^(\.\.(\/|\\|$))+|^[\\/]+/,
    "",
  );
  const candidate = join(root, relative);
  const file =
    candidate.startsWith(root) &&
    existsSync(candidate) &&
    statSync(candidate).isFile()
      ? candidate
      : join(root, "index.html");

  response.writeHead(200, {
    "Cache-Control": file.endsWith("index.html")
      ? "no-cache"
      : "public, max-age=31536000, immutable",
    "Content-Security-Policy":
      "default-src 'self'; connect-src 'self' http://127.0.0.1:* http://localhost:*; img-src 'self' data:; style-src 'self'; script-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
    "Content-Type": contentTypes[extname(file)] ?? "application/octet-stream",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
  });
  createReadStream(file).pipe(response);
}).listen(port, "0.0.0.0");
