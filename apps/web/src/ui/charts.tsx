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

export const fmt = {
  int: (value: number): string => integer.format(value),
  dec: (value: number): string => decimal.format(value),
  // Hífen não quebrável no sinal: "-R$ 1.089,19" não pode partir depois do
  // "-", que é o que acontece num tile estreito.
  brl: (value: number | null): string =>
    value === null ? "—" : currency.format(value).replace(/^-/, "‑"),
  liters: (value: number): string => `${decimal.format(value)} L`,
  pct: (value: number): string => `${integer.format(value * 100)}%`,
};

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
}

export function BarList({ data, format = fmt.int, tip }: BarListProps): JSX.Element {
  const max = Math.max(1, ...data.map((d) => Math.abs(d.value)));
  return (
    <ul className="bars">
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
}

export function Columns({ groups, series, format = fmt.brl }: ColumnsProps): JSX.Element {
  const max = Math.max(1, ...groups.flatMap((group) => group.values.map(Math.abs)));
  return (
    <div className="columns">
      <Legend items={series.map((label, index) => ({ label, color: seriesColor(index) }))} />
      <div className="plot" role="img" aria-label="Comparativo por lote">
        {groups.map((group, groupIndex) => (
          <div className="group" key={group.label}>
            {group.values.map((value, seriesIndex) => (
              <span
                key={series[seriesIndex]}
                className="col"
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
  const W = 300;
  const H = 64;
  const PAD = 8;
  if (points.length === 0) {
    return <p className="chart-empty">Sem leituras ainda.</p>;
  }
  const max = Math.max(...points.map((p) => p.value), 1);
  const min = Math.min(...points.map((p) => p.value), 0);
  const x = (index: number): number =>
    points.length === 1 ? W / 2 : PAD + (index * (W - 2 * PAD)) / (points.length - 1);
  const y = (value: number): number =>
    H - PAD - ((value - min) / (max - min || 1)) * (H - 2 * PAD);
  const path = points.map((p, i) => `${i === 0 ? "M" : "L"}${x(i)} ${y(p.value)}`).join(" ");
  const area = `${path} L${x(points.length - 1)} ${H} L${x(0)} ${H} Z`;

  return (
    <div>
      <svg
        className="spark"
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
        role="img"
        aria-label="Produção por data de coleta"
      >
        <path className="area" d={area} />
        <path className="line" d={path} vectorEffect="non-scaling-stroke" />
        {points.map((p, i) => (
          <circle
            key={p.label}
            className={`dot${i === points.length - 1 ? " current" : ""}`}
            cx={x(i)}
            cy={y(p.value)}
            r="4"
          >
            <title>
              {p.label}: {format(p.value)}
            </title>
          </circle>
        ))}
      </svg>
      <div className="spark-labels">
        <span>{points[0].label}</span>
        {points.length > 1 && <span>{points[points.length - 1].label}</span>}
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
