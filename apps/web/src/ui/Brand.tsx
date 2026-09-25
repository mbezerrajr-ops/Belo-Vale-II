/**
 * Marca, ícones e ilustrações — tudo SVG inline.
 *
 * Nada aqui é carregado de fora: a página precisa abrir no curral com sinal
 * ruim, e a CSP só permite recursos da própria origem.
 */

export function LogoMark({ size = 38 }: { size?: number }): JSX.Element {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 64 64"
      role="img"
      aria-label="Belo Vale II"
    >
      <defs>
        <linearGradient id="bv-g" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#3f8a5f" />
          <stop offset="1" stopColor="#1f4d3c" />
        </linearGradient>
        <clipPath id="bv-c">
          <circle cx="32" cy="32" r="31" />
        </clipPath>
      </defs>
      <circle cx="32" cy="32" r="31" fill="url(#bv-g)" />
      {/* colinas, recortadas no círculo: soltas, formavam um retângulo claro
          abaixo da marca */}
      <path
        d="M0 44c10-10 19-12 32-6s19 6 32 0v26H0z"
        fill="#f4efe4"
        opacity="0.18"
        clipPath="url(#bv-c)"
      />
      {/* cabeça de vaca estilizada */}
      <path
        d="M20 22c-4-3-8-3-9 1 2 3 5 4 8 4M44 22c4-3 8-3 9 1-2 3-5 4-8 4"
        fill="none"
        stroke="#fbf8f1"
        strokeWidth="3"
        strokeLinecap="round"
      />
      <path
        d="M22 25c0-6 4-9 10-9s10 3 10 9v9c0 6-4 10-10 10s-10-4-10-10z"
        fill="#fbf8f1"
      />
      <ellipse cx="32" cy="38" rx="6.5" ry="4.2" fill="#dd7436" opacity="0.9" />
      <circle cx="27.5" cy="27" r="1.7" fill="#1f4d3c" />
      <circle cx="36.5" cy="27" r="1.7" fill="#1f4d3c" />
      <circle cx="29.5" cy="38" r="1" fill="#1f4d3c" />
      <circle cx="34.5" cy="38" r="1" fill="#1f4d3c" />
    </svg>
  );
}

const ICON_PROPS = {
  width: 22,
  height: 22,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 2,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  "aria-hidden": true,
};

export const Icons = {
  painel: (): JSX.Element => (
    <svg {...ICON_PROPS}>
      <path d="M4 19V10M10 19V5M16 19v-7M22 19H2" />
    </svg>
  ),
  producao: (): JSX.Element => (
    <svg {...ICON_PROPS}>
      <path d="M9 3h6M10 3v3l-3 3v10a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2V9l-3-3V3" />
      <path d="M7 13h10" />
    </svg>
  ),
  revisao: (): JSX.Element => (
    <svg {...ICON_PROPS}>
      <path d="M4 5h16v14H4z" />
      <path d="M4 13h4l2 3h4l2-3h4" />
      <path d="M9 8.5l2 2 4-4" />
    </svg>
  ),
  animais: (): JSX.Element => (
    <svg {...ICON_PROPS}>
      <path d="M5 8c-2-2-4-1-4 1 1 1 3 1 4 1M19 8c2-2 4-1 4 1-1 1-3 1-4 1" />
      <path d="M7 9c0-3 2-5 5-5s5 2 5 5v5c0 3-2 5-5 5s-5-2-5-5z" />
      <path d="M9.5 10h.01M14.5 10h.01" strokeWidth="2.6" />
      <path d="M9.5 15.5h5" />
    </svg>
  ),
  insumos: (): JSX.Element => (
    <svg {...ICON_PROPS}>
      <path d="M12 21c-5 0-8-3-8-8 0-4 3-7 8-10 5 3 8 6 8 10 0 5-3 8-8 8z" />
      <path d="M12 21V9" />
      <path d="M12 13c-2 0-3.5-1-4.5-2.5M12 16c2 0 3.5-1 4.5-2.5" />
    </svg>
  ),
  medicoes: (): JSX.Element => (
    <svg {...ICON_PROPS}>
      <path d="M12 3s6 6.5 6 11a6 6 0 0 1-12 0c0-4.5 6-11 6-11z" />
      <path d="M9.5 15a2.5 2.5 0 0 0 2.5 2.5" />
    </svg>
  ),
  contas: (): JSX.Element => (
    <svg {...ICON_PROPS}>
      <circle cx="9" cy="8" r="3.5" />
      <path d="M2.5 20c0-3.5 3-6 6.5-6s6.5 2.5 6.5 6" />
      <circle cx="17" cy="9" r="2.5" />
      <path d="M16 14c3 0 5.5 2 5.5 5" />
    </svg>
  ),
  "minha-conta": (): JSX.Element => (
    <svg {...ICON_PROPS}>
      <circle cx="12" cy="8" r="4" />
      <path d="M4 21c0-4 3.5-7 8-7s8 3 8 7" />
    </svg>
  ),
  mais: (): JSX.Element => (
    <svg {...ICON_PROPS}>
      <rect x="4" y="4" width="6.5" height="6.5" rx="1.6" />
      <rect x="13.5" y="4" width="6.5" height="6.5" rx="1.6" />
      <rect x="4" y="13.5" width="6.5" height="6.5" rx="1.6" />
      <rect x="13.5" y="13.5" width="6.5" height="6.5" rx="1.6" />
    </svg>
  ),
  atualizar: (): JSX.Element => (
    <svg {...ICON_PROPS} width={18} height={18}>
      <path d="M20 11a8 8 0 0 0-14.3-4.9L4 8M4 4v4h4M4 13a8 8 0 0 0 14.3 4.9L20 16M20 20v-4h-4" />
    </svg>
  ),
  back: (): JSX.Element => (
    <svg {...ICON_PROPS}>
      <path d="M15 5l-7 7 7 7" />
    </svg>
  ),
  chevron: (): JSX.Element => (
    <svg {...ICON_PROPS}>
      <path d="M9 5l7 7-7 7" />
    </svg>
  ),
  search: (): JSX.Element => (
    <svg {...ICON_PROPS}>
      <circle cx="11" cy="11" r="6.5" />
      <path d="M20 20l-4-4" />
    </svg>
  ),
  logout: (): JSX.Element => (
    <svg {...ICON_PROPS} width={18} height={18}>
      <path d="M10 4H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h4M15 8l5 4-5 4M20 12H9" />
    </svg>
  ),
  // Os de ação, no tamanho do texto do botão.
  imprimir: (): JSX.Element => (
    <svg {...ICON_PROPS} width={18} height={18}>
      <path d="M7 9V3h10v6M7 17H5a2 2 0 0 1-2-2v-4a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v4a2 2 0 0 1-2 2h-2" />
      <path d="M7 14h10v7H7z" />
    </svg>
  ),
  camera: (): JSX.Element => (
    <svg {...ICON_PROPS}>
      <path d="M4 8h3l2-3h6l2 3h3a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V9a1 1 0 0 1 1-1z" />
      <circle cx="12" cy="13.5" r="3.5" />
    </svg>
  ),
  microfone: (): JSX.Element => (
    <svg {...ICON_PROPS}>
      <rect x="9" y="3" width="6" height="11" rx="3" />
      <path d="M5 11a7 7 0 0 0 14 0M12 18v3M8.5 21h7" />
    </svg>
  ),
  novo: (): JSX.Element => (
    <svg {...ICON_PROPS} width={18} height={18}>
      <path d="M12 5v14M5 12h14" />
    </svg>
  ),
  editar: (): JSX.Element => (
    <svg {...ICON_PROPS} width={18} height={18}>
      <path d="M4 20h4L19 9l-4-4L4 16v4zM13.5 6.5l4 4" />
    </svg>
  ),
  lote: (): JSX.Element => (
    <svg {...ICON_PROPS} width={18} height={18}>
      <path d="M4 8h13l-3-3M20 16H7l3 3" />
    </svg>
  ),
  brinco: (): JSX.Element => (
    <svg {...ICON_PROPS} width={18} height={18}>
      <path d="M12 3l7 4v6c0 4-3 7-7 8-4-1-7-4-7-8V7l7-4z" />
      <circle cx="12" cy="9.5" r="1.6" />
    </svg>
  ),
  juntar: (): JSX.Element => (
    <svg {...ICON_PROPS} width={18} height={18}>
      <path d="M6 4v4a4 4 0 0 0 4 4h4a4 4 0 0 1 4 4v4M18 4v4a4 4 0 0 1-4 4" />
    </svg>
  ),
  semSinal: (): JSX.Element => (
    <svg {...ICON_PROPS} width={18} height={18}>
      <path d="M3 3l18 18M8.5 16.5a5 5 0 0 1 7 0M5 13a10 10 0 0 1 5-2.7M19 13a10 10 0 0 0-2.3-1.6M2 9.5a15 15 0 0 1 4.3-2.9M22 9.5A15 15 0 0 0 11 5.1M12 20h.01" />
    </svg>
  ),
  guardado: (): JSX.Element => (
    <svg {...ICON_PROPS} width={18} height={18}>
      <path d="M7 18a4.5 4.5 0 0 1-.6-9A6 6 0 0 1 18 9.5a4 4 0 0 1-.5 8.5H7z" />
      <path d="M12 11v5M9.5 13.5 12 11l2.5 2.5" />
    </svg>
  ),
  olho: (): JSX.Element => (
    <svg {...ICON_PROPS} width={20} height={20}>
      <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  ),
  olhoFechado: (): JSX.Element => (
    <svg {...ICON_PROPS} width={20} height={20}>
      <path d="M3 3l18 18M10.6 5.1A10 10 0 0 1 12 5c6.5 0 10 7 10 7a17 17 0 0 1-3.2 4.1M6.6 6.6A17 17 0 0 0 2 12s3.5 7 10 7a9.6 9.6 0 0 0 5.4-1.6M9.9 9.9a3 3 0 0 0 4.2 4.2" />
    </svg>
  ),
  menu: (): JSX.Element => (
    <svg {...ICON_PROPS} width={18} height={18}>
      <circle cx="5" cy="12" r="1.4" />
      <circle cx="12" cy="12" r="1.4" />
      <circle cx="19" cy="12" r="1.4" />
    </svg>
  ),
};

export type IconName = keyof typeof Icons;

/** Colinas do horizonte, desenhadas duas vezes para a animação contínua. */
export function Hills(): JSX.Element {
  const wave =
    "M0 70 C 80 30, 160 30, 240 62 S 400 96, 480 60 S 560 30, 600 58 V120 H0 Z";
  return (
    <svg viewBox="0 0 1200 120" preserveAspectRatio="none" aria-hidden="true">
      <g fill="#3f8a5f" opacity="0.55">
        <path d={wave} />
        <path d={wave} transform="translate(600 0)" />
      </g>
      {/* A colina da frente é o chão da página: segue o tema, senão sobrava
          uma faixa creme sobre o fundo escuro. */}
      <g className="hill-front" transform="translate(0 28)">
        <path d={wave} />
        <path d={wave} transform="translate(600 0)" />
      </g>
    </svg>
  );
}

/** Silhuetas de vacas pastando no horizonte. */
export function Cows(): JSX.Element {
  const cow =
    "M6 12c0-4 3-7 8-7h14c4 0 7 2 8 5l1 3c3 0 5 1 5 3l-1 3h-4l-2-2h-2v9h-3l-1-7h-2l-1 7h-3l-1-7H14l-1 7h-3l-1-7H8l-1 7H4l-1-9c-2-1-3-3-3-5z";
  const positions = [60, 210, 330, 520, 700, 860, 1010, 1150];
  // Em tamanho real e repetido duas vezes (2.400 px): a faixa anda metade e
  // recomeça sem emenda. Esticada para a largura da tela, como antes, a vaca
  // virava uma salsicha no computador e um palito no celular.
  return (
    <svg viewBox="0 0 2400 40" width="2400" height="40" aria-hidden="true">
      <g fill="#14382b" opacity="0.7">
        {[0, 1200].flatMap((offset) =>
          positions.map((x, index) => (
            <path
              key={offset + x}
              d={cow}
              transform={`translate(${offset + x} 4) scale(${index % 3 === 0 ? 0.9 : 0.75})`}
            />
          )),
        )}
      </g>
    </svg>
  );
}
