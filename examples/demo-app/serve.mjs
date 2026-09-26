// Demo app for uxaudit on http://localhost:4173 (PORT to override).
// Sign in with demo@example.com / the password in DEMO_PASSWORD (default
// "pantry-demo"). Recipes live in memory; POST /__seed/empty or /__seed/many
// resets them (see seed.mjs).
import { readFileSync } from 'node:fs';
import { createServer } from 'node:http';

const app = readFileSync(new URL('./index.html', import.meta.url), 'utf8');
const login = readFileSync(new URL('./login.html', import.meta.url), 'utf8');
const port = Number(process.env.PORT ?? 4173);
const password = process.env.DEMO_PASSWORD ?? 'pantry-demo';
const sessions = new Set();
let recipes = [];

const LONG = 'おばあちゃんの味を再現した、じっくり煮込む具だくさんの肉じゃが（圧力鍋を使わない昔ながらの作り方、隠し味に味噌を少しだけ）';
const seeds = {
  empty: () => [],
  many: () => Array.from({ length: 60 }, (_, i) => (i % 7 === 0 ? `${LONG} #${i + 1}` : `レシピ ${i + 1}`)),
};

const html = (res, body, status = 200) => res.writeHead(status, { 'content-type': 'text/html; charset=utf-8' }).end(body);
const json = (res, body, status = 200) => res.writeHead(status, { 'content-type': 'application/json' }).end(JSON.stringify(body));
const signedIn = (req) => sessions.has(/sid=(\w+)/.exec(req.headers.cookie ?? '')?.[1]);
const readBody = (req) => new Promise((ok) => {
  let data = '';
  req.on('data', (c) => (data += c));
  req.on('end', () => ok(data));
});

createServer(async (req, res) => {
  const url = new URL(req.url, 'http://localhost');
  if (req.method === 'POST' && url.pathname.startsWith('/__seed/')) {
    const seed = seeds[url.pathname.slice('/__seed/'.length)];
    if (!seed) return json(res, { error: 'unknown seed' }, 400);
    recipes = seed();
    return json(res, { recipes: recipes.length });
  }
  if (url.pathname === '/login') {
    if (req.method === 'GET') return html(res, login);
    const form = new URLSearchParams(await readBody(req));
    if (form.get('email') === 'demo@example.com' && form.get('password') === password) {
      const sid = Math.random().toString(36).slice(2);
      sessions.add(sid);
      return res.writeHead(303, { location: '/', 'set-cookie': `sid=${sid}; Path=/; HttpOnly` }).end();
    }
    // Deliberate UX problem: a failed sign-in just reloads the empty form.
    return res.writeHead(303, { location: '/login' }).end();
  }
  if (!signedIn(req)) return res.writeHead(303, { location: '/login' }).end();
  if (url.pathname === '/api/recipes') {
    if (req.method === 'POST') {
      const { title } = JSON.parse(await readBody(req));
      recipes.push(title);
      return json(res, { ok: true }, 201);
    }
    return json(res, recipes);
  }
  if (url.pathname === '/') return html(res, app);
  res.writeHead(404).end('not found');
}).listen(port, () => console.log(`demo app on http://localhost:${port}`));
