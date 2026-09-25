import { useEffect, useRef, useState } from "react";

/**
 * A paisagem do login: vacas pastando atrás de camadas de papel recortado.
 *
 * É só decoração. O vídeo (`public/login/`) é o trecho do pasto recortado do
 * vídeo de referência, sem áudio, indo e voltando para o laço não dar pulo.
 * As camadas são desenhadas aqui, em SVG: nítidas em qualquer tela, com as
 * cores do tema, e cobrindo os cantos do recorte que ainda trazem o papel
 * desenhado no vídeo original.
 *
 * Fica fora de `/assets/`: lá o nginx guarda por um ano (os nomes levam o
 * conteúdo) e o service worker apaga o que não está na lista do build.
 */

const POSTER = "/login/login-cattle-poster.webp";
const VIDEO = "/login/login-cattle-animation.mp4";

/** A caixa do vídeo (256 × 300). O SVG usa a mesma caixa e o mesmo corte,
 *  presos à esquerda (`xMinYMid slice` aqui, `object-position: 0% 50%` no
 *  vídeo): as camadas ficam sobre a cena em qualquer tamanho de tela, e,
 *  quando sobra corte, ele cai na borda direita, a do cartão. */
const W = 256;
const H = 300;
/** As camadas crescem a partir daqui, perto da borda esquerda: é o lado que
 *  encosta no formulário, e ali todo anel precisa fechar dentro do painel —
 *  cortado pela borda, virava uma linha reta no meio do cartão. */
const CX = 56;
const CY = 170;

/** A janela da camada mais funda: só ali a cena aparece. Abaixo da faixa
 *  verde que o recorte traz no alto, à direita da que traz na esquerda, e
 *  com folga da borda direita. */
const WINDOW_START: [number, number] = [216, 54];
const WINDOW_CURVES: number[][] = [
  [226, 48, 231, 62, 230, 82],
  [228, 118, 222, 150, 226, 188],
  [230, 226, 226, 256, 204, 270],
  [178, 286, 134, 284, 96, 286],
  [60, 288, 30, 278, 26, 246],
  [22, 216, 34, 198, 50, 184],
  [72, 164, 70, 132, 92, 112],
  [118, 88, 150, 86, 178, 78],
  [198, 72, 208, 64, 216, 54],
];

/** Do fundo para a frente: verdes de pasto, depois papel, e por fim a cor do
 *  próprio cartão, que funde a moldura nele. Cada uma um pouco maior e
 *  deslocada na vertical, para os anéis não saírem concêntricos demais; na
 *  horizontal, sempre para a esquerda, senão um anel sumia atrás do outro. */
const LAYERS = [
  { scale: 1, dx: 0, dy: 0, color: "var(--leaf-3)" },
  { scale: 1.07, dx: -1, dy: 2, color: "var(--leaf-2)" },
  { scale: 1.15, dx: -1, dy: -1, color: "var(--leaf-1)" },
  { scale: 1.25, dx: -2, dy: 3, color: "var(--paper-2)" },
  { scale: 1.37, dx: -2, dy: -2, color: "var(--paper-1)" },
  { scale: 1.52, dx: 0, dy: 0, color: "var(--login-card)" },
];

function frameLayer(scale: number, dx: number, dy: number): string {
  const point = (x: number, y: number): string =>
    `${(CX + (x - CX) * scale + dx).toFixed(1)} ${(CY + (y - CY) * scale + dy).toFixed(1)}`;
  const curves = WINDOW_CURVES.map(
    ([x1, y1, x2, y2, x, y]) => `C ${point(x1, y1)}, ${point(x2, y2)}, ${point(x, y)}`,
  ).join(" ");
  // Um retângulo bem maior que a caixa, com a janela vazada (evenodd): no
  // corte `slice` a moldura nunca deixa ver a borda do vídeo.
  return `M ${-W} ${-H} H ${2 * W} V ${2 * H} H ${-W} Z M ${point(...WINDOW_START)} ${curves} Z`;
}

const FRAME = LAYERS.map((layer) => ({ ...layer, d: frameLayer(layer.scale, layer.dx, layer.dy) }));

/** No celular a paisagem vira uma faixa: o papel ondula só na borda de baixo. */
const WAVES = [
  { d: "M0 18 C 60 4, 124 30, 200 17 S 334 2, 400 14 V 64 H 0 Z", color: "var(--leaf-2)" },
  { d: "M0 29 C 72 15, 140 40, 214 28 S 344 13, 400 25 V 64 H 0 Z", color: "var(--leaf-1)" },
  { d: "M0 40 C 82 27, 154 50, 232 39 S 352 26, 400 36 V 64 H 0 Z", color: "var(--paper-1)" },
  { d: "M0 50 C 92 39, 172 60, 252 49 S 362 41, 400 47 V 64 H 0 Z", color: "var(--login-card)" },
];

/** Movimento reduzido ou economia de dados: fica a imagem parada. */
function prefersStill(): boolean {
  const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true;
  const saveData =
    (navigator as Navigator & { connection?: { saveData?: boolean } }).connection?.saveData ===
    true;
  return reduce || saveData;
}

function useStillLandscape(): boolean {
  const [still, setStill] = useState(prefersStill);
  useEffect(() => {
    const query = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    if (!query) return;
    const update = (): void => setStill(prefersStill());
    query.addEventListener?.("change", update);
    return () => query.removeEventListener?.("change", update);
  }, []);
  return still;
}

function LandscapeVideo(): JSX.Element {
  const ref = useRef<HTMLVideoElement>(null);
  useEffect(() => {
    const video = ref.current;
    if (!video) return;
    // O React não escreve `muted` como atributo, e há celular que só toca
    // sozinho o vídeo que já nasce mudo. Se o navegador recusar, fica o pôster.
    video.muted = true;
    const playing = video.play?.();
    if (playing) playing.catch(() => undefined);
  }, []);
  return (
    <video
      ref={ref}
      className="login-landscape-media"
      autoPlay
      muted
      loop
      playsInline
      preload="metadata"
      poster={POSTER}
    >
      <source src={VIDEO} type="video/mp4" />
    </video>
  );
}

export function LoginLandscape(): JSX.Element {
  const still = useStillLandscape();
  return (
    <div className="login-landscape" aria-hidden="true">
      {still ? (
        <img className="login-landscape-media" src={POSTER} alt="" decoding="async" />
      ) : (
        <LandscapeVideo />
      )}
      <svg
        className="paper paper-window"
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="xMinYMid slice"
        focusable="false"
      >
        {FRAME.map((layer) => (
          <path key={layer.scale} className="paper-layer" d={layer.d} fill={layer.color} fillRule="evenodd" />
        ))}
      </svg>
      <svg
        className="paper paper-wave"
        viewBox="0 0 400 64"
        preserveAspectRatio="none"
        focusable="false"
      >
        {WAVES.map((wave) => (
          <path key={wave.d} className="paper-layer" d={wave.d} fill={wave.color} />
        ))}
      </svg>
    </div>
  );
}
