import { useEffect, useRef, useState } from "react";

/**
 * A paisagem do login: vacas pastando numa janela de papel recortado.
 *
 * É só decoração. O vídeo (`public/login/`) é o trecho do vídeo de referência
 * com o pasto e a moldura de papel já desenhada nele (428×444 a partir de
 * 430,141), ampliado 2× com o Real-ESRGAN (`realesr-animevideov3`, feito para
 * vídeo: não pisca entre quadros), sem áudio, indo e voltando para o laço não
 * dar pulo. No computador aparece inteiro, como no
 * mockup; na faixa do celular, ampliado sobre as vacas, com a borda de papel
 * ondulada desenhada aqui.
 *
 * Fica fora de `/assets/`: lá o nginx guarda por um ano (os nomes levam o
 * conteúdo) e o service worker apaga o que não está na lista do build.
 */

const POSTER = "/login/login-cattle-poster.webp";
const VIDEO = "/login/login-cattle-animation.mp4";

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
      <svg className="paper-wave" viewBox="0 0 400 64" preserveAspectRatio="none" focusable="false">
        {WAVES.map((wave) => (
          <path key={wave.d} className="paper-layer" d={wave.d} fill={wave.color} />
        ))}
      </svg>
    </div>
  );
}
