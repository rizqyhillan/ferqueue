import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { dirname, extname, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = dirname(fileURLToPath(import.meta.url));
const port = Number(process.env.PORT || 4173);
const types = { '.html': 'text/html; charset=utf-8', '.css': 'text/css; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.svg': 'image/svg+xml', '.png': 'image/png', '.ico': 'image/x-icon' };
const server = createServer(async (request, response) => {
  try {
    const pathname = decodeURIComponent(new URL(request.url, 'http://localhost').pathname);
    const path = resolve(root, `.${pathname === '/' ? '/index.html' : pathname}`);
    const relative = path.slice(root.length + 1).split(sep).join('/');
    if (!path.startsWith(root + sep) || !/^(index\.html|src\/[\w.-]+\.(?:css|js)|assets\/[\w.-]+\.(?:svg|png|ico))$/.test(relative)) {
      response.writeHead(404).end('Halaman tidak ditemukan.');
      return;
    }
    const content = await readFile(path);
    response.writeHead(200, { 'Content-Type': types[extname(path)] || 'application/octet-stream', 'Cache-Control': 'no-cache', 'X-Content-Type-Options': 'nosniff' });
    response.end(content);
  } catch (error) {
    response.writeHead(error.code === 'ENOENT' ? 404 : 400).end('Halaman tidak ditemukan.');
  }
});
server.listen(port, '127.0.0.1', () => console.log(`FERQUEUE siap di http://localhost:${port}`));
server.on('error', error => { console.error(error.message); process.exitCode = 1; });
