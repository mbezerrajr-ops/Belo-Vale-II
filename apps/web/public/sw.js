/*
 * Guarda o app no celular para ele abrir sem sinal.
 *
 * Só o app: página, scripts, estilos e ícones desta origem. A API nunca passa
 * por aqui — nada de dado do rebanho, de token ou de resposta de servidor fica
 * guardado por este arquivo (o que precisa esperar sinal vai para a fila do
 * próprio app).
 *
 * - Todas as partes do app, pela lista que o build gera (asset-manifest.json):
 *   as telas são baixadas sob demanda, e uma tela nunca aberta também
 *   precisa abrir sem sinal.
 * - Página: da rede primeiro, para cada abertura com sinal pegar a versão
 *   nova; sem sinal, a última guardada. Versão nova detectada: guarda as
 *   partes novas antes da página nova, e tira as que ninguém usa mais.
 * - /assets/: têm o conteúdo no nome, então a guardada é sempre a certa.
 */

const CACHE = "belo-vale-app";

async function appFiles() {
  const response = await fetch("/asset-manifest.json", { cache: "no-store" });
  if (!response.ok) return null;
  const manifest = await response.json();
  const files = new Set();
  for (const entry of Object.values(manifest)) {
    if (entry.file) files.add(`/${entry.file}`);
    for (const css of entry.css ?? []) files.add(`/${css}`);
    for (const asset of entry.assets ?? []) files.add(`/${asset}`);
  }
  return files;
}

/** Guarda a versão atual inteira. A página por último: ela só passa a valer
 *  quando tudo o que ela usa já está guardado. */
let preparing = null;
async function prepareVersion() {
  const cache = await caches.open(CACHE);
  const page = await fetch("/", { cache: "no-store" });
  const files = await appFiles();
  if (!page.ok || files === null) return;
  // Um a um: uma parte que falhar não impede as outras de ficar.
  await Promise.all(
    [...files].map(async (file) => {
      if (await cache.match(file)) return;
      const response = await fetch(file);
      if (!response.ok) throw new Error("Uma parte do aplicativo não pôde ser guardada.");
      await cache.put(file, response);
    }),
  );
  const previous = await cache.match("/__current-app-files");
  const previousFiles = previous ? await previous.json() : [];
  await cache.put("/__previous-app-files", new Response(JSON.stringify(previousFiles)));
  await cache.put("/__current-app-files", new Response(JSON.stringify([...files])));
  await cache.put("/", page);
  for (const request of await cache.keys()) {
    const path = new URL(request.url).pathname;
    if (path.startsWith("/assets/") && !files.has(path) && !previousFiles.includes(path)) await cache.delete(request);
  }
}

function precache() {
  preparing ??= prepareVersion().finally(() => { preparing = null; });
  return preparing;
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

async function page(event) {
  const cache = await caches.open(CACHE);
  try {
    const response = await fetch(event.request);
    if (response.ok) {
      const saved = await cache.match("/");
      const [fresh, old] = await Promise.all([
        response.clone().text(),
        saved ? saved.text() : Promise.resolve(""),
      ]);
      // Versão nova do app: guarda tudo dela, em segundo plano.
      if (fresh !== old) event.waitUntil(precache().catch(() => undefined));
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
    event.respondWith(page(event));
  } else if (url.pathname.startsWith("/assets/")) {
    event.respondWith(asset(request));
  } else if (/\.(svg|png|webp|json|webmanifest)$/.test(url.pathname) && url.pathname !== "/asset-manifest.json") {
    // A imagem parada do login entra aqui (sem sinal, o pasto ainda aparece);
    // o vídeo não: o Safari o pede em pedaços, e guardado inteiro não toca.
    event.respondWith(other(request));
  }
});
