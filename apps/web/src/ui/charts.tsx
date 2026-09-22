/**
 * Gráficos em SVG e CSS, sem biblioteca.
 *
 * Regras fixas (validadas para daltonismo e leitura no sol):
 * - cores de série em ordem fixa — a cor segue a entidade, nunca a posição;
 * - marcas finas, ponta arredondada, 2px de gap entre marcas vizinhas;
 * - texto sempre em tinta, nunca na cor da série; a identidade vem do swatch;
 * - legenda quando há mais de uma série; tooltip por marca; visão em tabela.
 */

import { useEffect, useState, type CSSProperties, type ReactNode } from "react";

import { useCountUp } from "./useCountUp";

const integer = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 0 });
const decimal = new Intl.NumberFormat("pt-BR", {
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
});
const currency = new Intl.NumberFormat("pt-BR", {
  style: "currency",
  currency: "BRL",
});
const wholeCurrency = new Intl.NumberFormat("pt-BR", {
  style: "currency",
  currency: "BRL",
  maximumFractionDigits: 0,
});

export const fmt = {
  int: (value: number): string => integer.format(value),
  dec: (value: number): string => decimal.format(value),
  // Hífen não quebrável no sinal: "-R$ 1.089,19" não pode partir depois do
  // "-", que é o que acontece num tile estreito.
  brl: (value: number | null): string =>
    value === null ? "—" : currency.format(value).replace(/^-/, "‑"),
  liters: (value: number): string => `${decimal.format(value)} L`,
  pct: (value: number): string => `${integer.format(value * 100)}%`,
  /** Real sem centavos: para eixo, onde o centavo só ocupa lugar. */
  brlWhole: (value: number): string => wholeCurrency.format(value),
};

/** O topo "redondo" da escala (1, 2, 2,5 ou 5 vezes uma potência de 10). */
export function niceCeil(value: number): number {
  if (value <= 0) return 1;
  const base = 10 ** Math.floor(Math.log10(value));
  for (const step of [1, 2, 2.5, 5, 10]) {
    if (value <= step * base) return step * base;
  }
  return 10 * base;
}

export const SERIES = [
  "var(--series-1)",
  "var(--series-2)",
  "var(--series-3)",
  "var(--series-4)",
  "var(--series-5)",
] as const;

function seriesColor(index: number): string {
  // Além do 5º slot a paleta não é mais segura: dobra em cinza neutro, e a
  // legenda + tabela carregam a identidade.
  return index < SERIES.length ? SERIES[index] : "var(--line-strong)";
}

function stageDone(): boolean {
  return import.meta.env.MODE === "test";
}

// ---------- cartão ----------

interface ChartCardProps {
  title: string;
  description?: string;
  index?: number;
  aside?: ReactNode;
  children: ReactNode;
}

export function ChartCard({
  title,
  description,
  index = 0,
  aside,
  children,
}: ChartCardProps): JSX.Element {
  return (
    <section className="chart-card" style={{ "--i": index } as CSSProperties}>
      <header>
        <h3>{title}</h3>
        {aside}
      </header>
      {description && <p className="desc">{description}</p>}
      {children}
    </section>
  );
}

// ---------- estat ----------

interface StatTileProps {
  label: string;
  value: number | null;
  format?: (value: number) => string;
  hint?: string;
  color?: string;
  index?: number;
}

export function StatTile({
  label,
  value,
  format = fmt.int,
  hint,
  color,
  index = 0,
}: StatTileProps): JSX.Element {
  const animated = useCountUp(value ?? 0);
  const shown = value === null ? "—" : format(animated);
  return (
    <div
      className="kpi"
      style={{ "--i": index, "--kpi-color": color } as CSSProperties}
    >
      <span>{label}</span>
      <strong className={value !== null && value < 0 ? "negative" : undefined}>
        {shown}
      </strong>
      {hint && <small>{hint}</small>}
    </div>
  );
}

// ---------- legenda ----------

export function Legend({
  items,
}: {
  items: Array<{ label: string; color: string }>;
}): JSX.Element {
  return (
    <div className="legend" aria-label="Legenda">
      <ul>
        {items.map((item) => (
          <li key={item.label}>
            <span className="swatch" style={{ "--swatch": item.color } as CSSProperties} />
            {item.label}
          </li>
        ))}
      </ul>
    </div>
  );
}

// ---------- barras horizontais ----------

export interface BarDatum {
  label: string;
  value: number;
  /** Índice da série para cor. Ausente = uma só série, verde. */
  series?: number;
  dim?: boolean;
}

interface BarListProps {
  data: BarDatum[];
  format?: (value: number) => string;
  /** Texto do tooltip; padrão é "rótulo: valor". */
  tip?: (datum: BarDatum) => string;
  /**
   * O topo da escala. Duas listas da mesma medida (maiores e menores
   * produções) comparam no mesmo topo: com a escala de cada uma, 8,5 L
   * aparecia com a barra quase cheia.
   */
  max?: number;
}

export function BarList({ data, format = fmt.int, tip, max: top }: BarListProps): JSX.Element {
  const max = top ?? Math.max(1, ...data.map((d) => Math.abs(d.value)));
  // A coluna do valor tem a largura do maior valor: as trilhas terminam
  // todas no mesmo ponto, em vez de dançarem com o tamanho do número.
  const valueWidth = Math.max(...data.map((d) => format(d.value).length), 1);
  return (
    <ul className="bars" style={{ "--value-w": `${valueWidth + 1}ch` } as CSSProperties}>
      {data.map((datum, index) => (
        <li
          key={datum.label}
          className={datum.dim ? "dim" : undefined}
          data-tip={tip ? tip(datum) : `${datum.label}: ${format(datum.value)}`}
          tabIndex={0}
        >
          <span className="bar-label">{datum.label}</span>
          <span className="bar-track" aria-hidden="true">
            <span
              className="bar-fill"
              style={
                {
                  "--w": `${Math.max(1.5, (Math.abs(datum.value) / max) * 100)}%`,
                  "--bar-color": seriesColor(datum.series ?? 0),
                  "--i": index,
                } as CSSProperties
              }
            />
          </span>
          <span className="bar-value">{format(datum.value)}</span>
        </li>
      ))}
    </ul>
  );
}

// ---------- rosca ----------

export interface Slice {
  label: string;
  value: number;
}

interface DonutProps {
  data: Slice[];
  centerLabel: string;
  format?: (value: number) => string;
}

export function Donut({ data, centerLabel, format = fmt.int }: DonutProps): JSX.Element {
  const total = data.reduce((sum, slice) => sum + slice.value, 0);
  const [ready, setReady] = useState(stageDone());
  useEffect(() => {
    if (ready) return;
    const frame = requestAnimationFrame(() => setReady(true));
    return () => cancelAnimationFrame(frame);
  }, [ready]);

  const R = 56;
  const C = 2 * Math.PI * R;
  const GAP = data.length > 1 ? 2.5 : 0;
  const animatedTotal = useCountUp(total);

  let offset = 0;
  const arcs = data.map((slice, index) => {
    const share = total > 0 ? slice.value / total : 0;
    const length = Math.max(0, share * C - GAP);
    const arc = {
      key: slice.label,
      color: seriesColor(index),
      dasharray: ready ? `${length} ${C - length}` : `0 ${C}`,
      dashoffset: -offset,
      share,
      slice,
    };
    offset += share * C;
    return arc;
  });

  return (
    <div className="donut">
      <svg viewBox="0 0 150 150" role="img" aria-label={`${centerLabel}: ${format(total)}`}>
        <circle cx="75" cy="75" r={R} fill="none" stroke="var(--track)" strokeWidth="18" />
        <g transform="rotate(-90 75 75)">
          {arcs.map((arc) => (
            <circle
              key={arc.key}
              className="arc"
              cx="75"
              cy="75"
              r={R}
              stroke={arc.color}
              strokeDasharray={arc.dasharray}
              strokeDashoffset={arc.dashoffset}
            >
              <title>
                {arc.slice.label}: {format(arc.slice.value)} ({fmt.pct(arc.share)})
              </title>
            </circle>
          ))}
        </g>
        <text className="center" x="75" y="80">
          {format(animatedTotal)}
        </text>
        <text className="center-label" x="75" y="97">
          {centerLabel.toUpperCase()}
        </text>
      </svg>
      <ul className="donut-legend">
        {arcs.map((arc) => (
          <li key={arc.key}>
            <span className="swatch" style={{ "--swatch": arc.color } as CSSProperties} />
            <span>{arc.slice.label}</span>
            <strong>{format(arc.slice.value)}</strong>
            <small>{fmt.pct(arc.share)}</small>
          </li>
        ))}
      </ul>
    </div>
  );
}

// ---------- colunas agrupadas ----------

export interface ColumnGroup {
  label: string;
  values: number[];
  /** Linha pequena sob o rótulo, com sinal (ex.: lucro). */
  note?: { text: string; sign: "pos" | "neg" | "zero" };
}

interface ColumnsProps {
  groups: ColumnGroup[];
  series: string[];
  format?: (value: number) => string;
  /** Rótulos do eixo; padrão, real sem centavos. */
  axisFormat?: (value: number) => string;
}

export function Columns({
  groups,
  series,
  format = fmt.brl,
  axisFormat = fmt.brlWhole,
}: ColumnsProps): JSX.Element {
  // A escala vai até um valor redondo, e as linhas de grade (a cada quarto)
  // têm o valor escrito ao lado: sem isto, as colunas só diziam "maior" e
  // "menor".
  const max = niceCeil(Math.max(1, ...groups.flatMap((group) => group.values.map(Math.abs))));
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((share) => share * max);
  return (
    <div className="columns">
      <Legend items={series.map((label, index) => ({ label, color: seriesColor(index) }))} />
      <div className="columns-frame">
        <div className="axis" aria-hidden="true">
          {ticks.map((tick) => (
            <span key={tick} style={{ bottom: `${(tick / max) * 100}%` }}>
              {axisFormat(tick)}
            </span>
          ))}
        </div>
      <div className="plot" role="img" aria-label="Comparativo por lote">
        {groups.map((group, groupIndex) => (
          <div className="group" key={group.label}>
            {group.values.map((value, seriesIndex) => (
              <span
                key={series[seriesIndex]}
                className={`col${groupIndex === groups.length - 1 && groups.length > 1 ? " tip-end" : groupIndex === 0 && groups.length > 1 ? " tip-start" : ""}`}
                data-tip={`${group.label} · ${series[seriesIndex]}: ${format(value)}`}
                tabIndex={0}
                style={
                  {
                    "--h": `${Math.max(1.5, (Math.abs(value) / max) * 100)}%`,
                    "--col-color": seriesColor(seriesIndex),
                    "--i": groupIndex,
                  } as CSSProperties
                }
              />
            ))}
          </div>
        ))}
      </div>
      </div>
      <div className="labels">
        {groups.map((group) => (
          <div key={group.label}>
            <strong>{group.label}</strong>
            {group.note && <small className={group.note.sign}>{group.note.text}</small>}
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------- sparkline ----------

export interface SparkPoint {
  label: string;
  value: number;
}

export function Sparkline({
  points,
  format = fmt.dec,
}: {
  points: SparkPoint[];
  format?: (value: number) => string;
}): JSX.Element {
  // A linha e o preenchimento esticam com o cartão; os pontos e os rótulos
  // ficam em HTML por cima, então não viram elipses no computador.
  const W = 300;
  const H = 80;
  const PAD = 10;
  if (points.length === 0) {
    return <p className="chart-empty">Sem leituras ainda.</p>;
  }
  const max = Math.max(...points.map((p) => p.value), 1);
  const x = (index: number): number =>
    points.length === 1 ? W / 2 : PAD + (index * (W - 2 * PAD)) / (points.length - 1);
  // O chão da escala é o zero: litro não começa em outro lugar.
  const y = (value: number): number => H - (value / max) * (H - PAD * 2.4);
  const path = points.map((p, i) => `${i === 0 ? "M" : "L"}${x(i)} ${y(p.value)}`).join(" ");
  const area = `${path} L${x(points.length - 1)} ${H} L${x(0)} ${H} Z`;
  // Poucas coletas: cada ponto diz o valor e a data. Muitas: primeira e última.
  const labelAll = points.length <= 6;
  const edge = (i: number): string =>
    points.length > 1 && i === 0 ? " start" : points.length > 1 && i === points.length - 1 ? " end" : "";

  return (
    <div className="trend">
      <div className="trend-plot">
        <svg
          className="spark"
          viewBox={`0 0 ${W} ${H}`}
          preserveAspectRatio="none"
          role="img"
          aria-label="Produção por data de coleta"
        >
          <path className="spark-area" d={area} />
          <path className="line" d={path} vectorEffect="non-scaling-stroke" />
        </svg>
        {points.map((p, i) => (
          <span
            key={p.label}
            className={`trend-dot${i === points.length - 1 ? " current" : ""}${edge(i) ? ` tip-${edge(i).trim()}` : ""}`}
            style={{ left: `${(x(i) / W) * 100}%`, top: `${(y(p.value) / H) * 100}%` }}
            data-tip={`${p.label}: ${format(p.value)}`}
            tabIndex={0}
          />
        ))}
        {labelAll &&
          points.map((p, i) => (
            <span
              key={`v-${p.label}`}
              className={`trend-value${edge(i)}${i === points.length - 1 ? " current" : ""}`}
              style={{ left: `${(x(i) / W) * 100}%`, top: `${(y(p.value) / H) * 100}%` }}
            >
              {format(p.value)}
            </span>
          ))}
      </div>
      <div className="trend-dates">
        {points.map((p, i) =>
          labelAll || i === 0 || i === points.length - 1 ? (
            <span key={p.label} className={edge(i).trim()} style={{ left: `${(x(i) / W) * 100}%` }}>
              {p.label}
            </span>
          ) : null,
        )}
      </div>
    </div>
  );
}

// ---------- visão em tabela ----------

export function TableView({
  columns,
  rows,
}: {
  columns: string[];
  rows: Array<Array<string | number>>;
}): JSX.Element {
  return (
    <details className="table-view">
      <summary>Ver como tabela</summary>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              {columns.map((column, index) => (
                <th key={column} className={index > 0 ? "num" : undefined}>
                  {column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, rowIndex) => (
              <tr key={rowIndex}>
                {row.map((cell, cellIndex) => (
                  <td key={cellIndex} className={cellIndex > 0 ? "num" : undefined}>
                    {cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}
