import { useEffect, useState } from "react";

import { fetchSourceMedia } from "../../api/client";

/**
 * A folha ou a gravação de onde a leitura saiu, ao lado das propostas.
 *
 * Quem revisa aprova o que o modelo entendeu; para isso precisa ver a folha,
 * ou ouvir a gravação, sem trocar de tela. O arquivo vem da própria API, com
 * o mesmo login de tudo: o navegador não manda o token num `<img src>` ou
 * `<audio src>` comum, então a tela busca o arquivo e o mostra como `blob:`.
 */

type FetchFn = (url: string, token: string) => Promise<Blob>;

interface Props {
  url: string;
  kind: "photo" | "audio" | "text";
  token: string;
  onFetch?: FetchFn;
}

type State = { status: "loading" } | { status: "ready"; src: string } | { status: "error" };

export function SourceMedia({ url, kind, token, onFetch = fetchSourceMedia }: Props): JSX.Element | null {
  const [state, setState] = useState<State>({ status: "loading" });

  useEffect(() => {
    let vivo = true;
    let src: string | null = null;
    setState({ status: "loading" });
    onFetch(url, token)
      .then((blob) => {
        if (!vivo) return;
        src = URL.createObjectURL(blob);
        setState({ status: "ready", src });
      })
      .catch(() => {
        if (vivo) setState({ status: "error" });
      });
    return () => {
      vivo = false;
      // O arquivo ocupa memória enquanto a URL existir.
      if (src) URL.revokeObjectURL(src);
    };
  }, [url, token, onFetch]);

  if (state.status === "error") {
    return <small className="source-media-error">Não foi possível abrir o arquivo.</small>;
  }
  if (state.status === "loading") return null;

  if (kind === "audio") {
    return (
      <span className="source-audio">
        <audio controls preload="metadata" src={state.src} aria-label="Ouvir a gravação" />
      </span>
    );
  }
  return (
    <a className="source-photo" href={state.src} target="_blank" rel="noreferrer">
      <img src={state.src} alt="" />
      <span>Ver a folha</span>
    </a>
  );
}
