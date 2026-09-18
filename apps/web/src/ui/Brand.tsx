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
      </defs>
      <circle cx="32" cy="32" r="31" fill="url(#bv-g)" />
      {/* colinas */}
      <path
        d="M4 44c9-10 18-12 28-6s17 6 28 0v18H4z"
        fill="#f4efe4"
        opacity="0.18"
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
  animais: (): JSX.Element => (
    <svg {...ICON_PROPS}>
      <path d="M5 8c-2-2-4-1-4 1 1 1 3 1 4 1M19 8c2-2 4-1 4 1-1 1-3 1-4 1" />
      <path d="M7 9c0-3 2-5 5-5s5 2 5 5v5c0 3-2 5-5 5s-5-2-5-5z" />
      <path d="M9.5 10h.01M14.5 10h.01" strokeWidth="2.6" />
      <path d="M9.5 15.5h5" />
    </svg>
  ),
  fichas: (): JSX.Element => (
    <svg {...ICON_PROPS}>
      <path d="M4 8a2 2 0 0 1 2-2h2l1.5-2h5L16 6h2a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2z" />
      <circle cx="12" cy="12.5" r="3.2" />
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
      <g fill="#f4efe4" transform="translate(0 28)">
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
  return (
    <svg viewBox="0 0 1200 40" preserveAspectRatio="none" aria-hidden="true">
      <g fill="#14382b" opacity="0.7">
        {positions.map((x, index) => (
          <path
            key={x}
            d={cow}
            transform={`translate(${x} 4) scale(${index % 3 === 0 ? 0.9 : 0.75})`}
          />
        ))}
      </g>
    </svg>
  );
}
