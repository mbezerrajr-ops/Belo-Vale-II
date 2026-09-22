/*
 * Guarda o app no celular para ele abrir sem sinal.
 *
 * Só o app: página, scripts, estilos e ícones desta origem. A API nunca passa
 * por aqui — nada de dado do rebanho, de token ou de resposta de servidor fica
 * guardado por este arquivo (o que precisa esperar sinal vai para a fila do
 * próprio app).
 *
 * - Página: da rede primeiro, para cada abertura com sinal pegar a versão
 *   nova; sem sinal, a última guardada.
 * - /assets/: têm o conteúdo no nome, então a guardada é sempre a certa.
 *   Quando uma página nova é guardada, os arquivos que ela não usa mais saem.
 */

const CACHE = "belo-vale-app";

/**
 * Na instalação, guarda a página e os arquivos que ela usa. Sem isto, a
 * primeira visita (que o service worker ainda não controla) não guardava
 * nada, e recarregar sem sinal logo depois falhava.
 */
async function precache() {
  const cache = await caches.open(CACHE);
  const response = await fetch("/", { cache: "no-store" });
  if (!response.ok) return;
  const html = await response.clone().text();
  await cache.put("/", response);
  const assets = Array.from(new Set(Array.from(html.matchAll(/\/assets\/[^"'\s)]+/g), (match) => match[0])));
  await cache.addAll(assets);
}

self.addEventListener("install", (event) => {
  event.waitUntil(precache().catch(() => undefined).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((names) =>
      Promise.all(names.filter((name) => name !== CACHE).map((name) => caches.delete(name))),
    ),
  );
});

function isAppRequest(request, url) {
  return (
    request.method === "GET" &&
    url.origin === self.location.origin &&
    !url.pathname.startsWith("/api/") &&
    url.pathname !== "/healthz"
  );
}

/** Tira do cache os /assets/ que a página nova não referencia. */
async function prune(cache, html) {
  const used = new Set(Array.from(html.matchAll(/\/assets\/[^"'\s)]+/g), (match) => match[0]));
  for (const request of await cache.keys()) {
    const path = new URL(request.url).pathname;
    if (path.startsWith("/assets/") && !used.has(path)) await cache.delete(request);
  }
}

async function page(request) {
  const cache = await caches.open(CACHE);
  try {
    const response = await fetch(request);
    if (response.ok) {
      const copy = response.clone();
      // Toda rota do app é a mesma página: guarda uma vez só, como "/".
      await cache.put("/", copy.clone());
      await prune(cache, await copy.text());
    }
    return response;
  } catch (error) {
    const saved = await cache.match("/");
    if (saved) return saved;
    throw error;
  }
}

async function asset(request) {
  const cache = await caches.open(CACHE);
  const saved = await cache.match(request);
  if (saved) return saved;
  const response = await fetch(request);
  if (response.ok) await cache.put(request, response.clone());
  return response;
}

async function other(request) {
  const cache = await caches.open(CACHE);
  try {
    const response = await fetch(request);
    if (response.ok) await cache.put(request, response.clone());
    return response;
  } catch (error) {
    const saved = await cache.match(request);
    if (saved) return saved;
    throw error;
  }
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  const url = new URL(request.url);
  if (!isAppRequest(request, url)) return;
  if (request.mode === "navigate") {
    event.respondWith(page(request));
  } else if (url.pathname.startsWith("/assets/")) {
    event.respondWith(asset(request));
  } else if (/\.(svg|png|json|webmanifest)$/.test(url.pathname)) {
    event.respondWith(other(request));
  }
});
