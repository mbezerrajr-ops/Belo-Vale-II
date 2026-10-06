import { useEffect, useRef, useState } from "react";

/**
 * A paisagem do login.
 *
 * É só decoração. Fica fora de `/assets/`: lá o nginx guarda por um ano (os
 * nomes levam o conteúdo) e o service worker apaga o que não está na lista
 * do build.
 *
 * - Computador (e celular deitado): vacas pastando na janela de papel
 *   recortado, em vídeo. É um trecho do vídeo de referência, com a moldura
 *   já desenhada, 428×444 a partir de 430,141, ampliado 2× com o Real-ESRGAN
 *   (`realesr-animevideov3`: não pisca entre quadros), sem áudio, indo e
 *   voltando para o laço não dar pulo.
 * - Celular e tablet em pé: só a paisagem, parada, no pé do cartão, sem
 *   vacas nem moldura (pedido do titular, 06/10/2026: as vacas grandes
 *   ficavam estranhas na tela pequena). É o fundo da mesma arte — árvore,
 *   morros, celeiro, pasto e cerca —, com as vacas ao longe apagadas; o céu
 *   se desfaz no papel do cartão.
 */

/** O mesmo corte do CSS em que o cartão vira duas colunas. */
const WIDE_LAYOUT = "(min-width: 880px), (min-width: 560px) and (max-height: 500px)";

const WIDE = {
  video: "/login/login-cattle-animation.mp4",
  poster: "/login/login-cattle-poster.webp",
};

const NARROW_IMAGE = "/login/login-landscape-mobile.webp";

function matches(query: string): boolean {
  return window.matchMedia?.(query).matches === true;
}

/** Movimento reduzido ou economia de dados: fica a imagem parada. */
function prefersStill(): boolean {
  const saveData =
    (navigator as Navigator & { connection?: { saveData?: boolean } }).connection?.saveData ===
    true;
  return matches("(prefers-reduced-motion: reduce)") || saveData;
}

/** Acompanha uma media query (girar o celular troca o layout). */
function useMediaQuery(query: string, read: () => boolean): boolean {
  const [value, setValue] = useState(read);
  useEffect(() => {
    const list = window.matchMedia?.(query);
    if (!list) return;
    const update = (): void => setValue(read());
    list.addEventListener?.("change", update);
    return () => list.removeEventListener?.("change", update);
  }, [query, read]);
  return value;
}

const readWide = (): boolean => matches(WIDE_LAYOUT);

function LandscapeVideo({ video, poster }: { video: string; poster: string }): JSX.Element {
  const ref = useRef<HTMLVideoElement>(null);
  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    // O React não escreve `muted` como atributo, e há celular que só toca
    // sozinho o vídeo que já nasce mudo. Se o navegador recusar, fica o pôster.
    element.muted = true;
    const playing = element.play?.();
    if (playing) playing.catch(() => undefined);
  }, [video]);
  return (
    <video
      ref={ref}
      className="login-landscape-media"
      autoPlay
      muted
      loop
      playsInline
      preload="metadata"
      poster={poster}
    >
      <source src={video} type="video/mp4" />
    </video>
  );
}

export function LoginLandscape(): JSX.Element {
  const still = useMediaQuery("(prefers-reduced-motion: reduce)", prefersStill);
  const wide = useMediaQuery(WIDE_LAYOUT, readWide);
  return (
    <div className="login-landscape" aria-hidden="true">
      {!wide ? (
        <img className="login-landscape-media" src={NARROW_IMAGE} alt="" decoding="async" />
      ) : still ? (
        <img className="login-landscape-media" src={WIDE.poster} alt="" decoding="async" />
      ) : (
        <LandscapeVideo video={WIDE.video} poster={WIDE.poster} />
      )}
    </div>
  );
}

/** O galho do canto de cima no celular, como no mockup. Balança devagar
 *  pelo CSS, sem outro vídeo para baixar. */
export function LoginBranch(): JSX.Element {
  return <img className="login-branch" src="/login/login-branch.webp" alt="" aria-hidden="true" decoding="async" />;
}
