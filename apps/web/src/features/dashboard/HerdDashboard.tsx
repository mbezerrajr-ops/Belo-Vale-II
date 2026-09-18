import { useEffect, useState } from "react";

import { getDashboard } from "../../api/client";
import type { DashboardFilters, DashboardSummary } from "../../api/types";

/**
 * Painel do rebanho.
 *
 * Porta os indicadores da plataforma legada sobre os dados no banco. As barras
 * são divs com largura proporcional, sem biblioteca de gráficos: a página
 * precisa abrir com sinal ruim, e um gráfico de barras não justifica 200 kB.
 *
 * Quando falta o preço do leite, receita e lucro aparecem como "—", nunca como
 * R$ 0,00 — não saber quanto se recebe é diferente de não receber nada.
 */

type LoadFn = (
  token: string,
  filters: DashboardFilters,
) => Promise<DashboardSummary>;

interface Props {
  token: string;
  onLoad?: LoadFn;
}

const currency = new Intl.NumberFormat("pt-BR", {
  style: "currency",
  currency: "BRL",
});
const decimal = new Intl.NumberFormat("pt-BR", {
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
});
const integer = new Intl.NumberFormat("pt-BR");

function money(value: number | null): string {
  return value === null ? "—" : currency.format(value);
}

function Bars({
  data,
  format,
}: {
  data: Array<[string, number]>;
  format?: (value: number) => string;
}): JSX.Element {
  const max = Math.max(1, ...data.map(([, value]) => value));
  return (
    <ul className="bars">
      {data.map(([label, value]) => (
        <li key={label}>
          <span className="bar-label">{label}</span>
          <span className="bar-track">
            <span
              className="bar-fill"
              style={{ width: `${Math.round((value / max) * 100)}%` }}
            />
          </span>
          <span className="bar-value">
            {format ? format(value) : integer.format(value)}
          </span>
        </li>
      ))}
    </ul>
  );
}

export function HerdDashboard({
  token,
  onLoad = getDashboard,
}: Props): JSX.Element {
  const [panel, setPanel] = useState<DashboardSummary | null>(null);
  const [filters, setFilters] = useState<DashboardFilters>({});
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    onLoad(token, filters)
      .then((loaded) => {
        if (!cancelled) setPanel(loaded);
      })
      .catch((caught: unknown) => {
        const body = (caught as { body?: { detail?: string } })?.body;
        if (!cancelled) {
          setError(body?.detail ?? "Não foi possível carregar o painel.");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [token, filters, onLoad]);

  if (error) return <p role="alert">{error}</p>;
  if (panel === null) return <p>Carregando painel…</p>;

  const lotNames = panel.lots.map((lot) => lot.lote);

  return (
    <section className="dashboard">
      <h2>Painel do rebanho</h2>

      <div className="filters">
        <div>
          <label htmlFor="filtro-lote">Lote</label>
          <select
            id="filtro-lote"
            value={filters.lote ?? ""}
            onChange={(event) =>
              setFilters((current) => ({
                ...current,
                lote: event.target.value || undefined,
              }))
            }
          >
            <option value="">Todos</option>
            {lotNames.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="filtro-situacao">Situação</label>
          <select
            id="filtro-situacao"
            value={filters.situacao ?? ""}
            onChange={(event) =>
              setFilters((current) => ({
                ...current,
                situacao: event.target.value || undefined,
              }))
            }
          >
            <option value="">Todas</option>
            {Object.keys(panel.by_situation).map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="filtro-data">Data da coleta</label>
          <select
            id="filtro-data"
            value={filters.measuredOn ?? panel.measured_on ?? ""}
            onChange={(event) =>
              setFilters((current) => ({
                ...current,
                measuredOn: event.target.value || undefined,
              }))
            }
          >
            {panel.available_dates.map((day) => (
              <option key={day} value={day}>
                {day}
              </option>
            ))}
          </select>
        </div>
      </div>

      {panel.measured_on === null && (
        <p className="warning">
          Nenhuma medição registrada ainda. Envie uma ficha para ver produção e
          receita.
        </p>
      )}

      {panel.milk_price === null && (
        <p className="warning">
          Preço do leite não definido — receita e lucro não podem ser
          calculados. Ajuste em Insumos.
        </p>
      )}

      {panel.measured_on !== null &&
        panel.animals_with_reading > 0 &&
        panel.animals_with_reading < panel.total_animals && (
          <p className="warning">
            Nesta data há leitura de {integer.format(panel.animals_with_reading)}{" "}
            de {integer.format(panel.total_animals)} animais. O custo mostrado é o
            do lote inteiro, então receita e lucro ficam subestimados — compare
            apenas datas com cobertura parecida.
          </p>
        )}

      <div className="kpis">
        <div className="kpi">
          <span>Animais</span>
          <strong>{integer.format(panel.total_animals)}</strong>
        </div>
        <div className="kpi">
          <span>Com leitura</span>
          <strong>{integer.format(panel.animals_with_reading)}</strong>
        </div>
        <div className="kpi">
          <span>Produção/dia</span>
          <strong>{decimal.format(panel.total_production)} L</strong>
        </div>
        <div className="kpi">
          <span>Custo/dia</span>
          <strong>{money(panel.total_feed_cost)}</strong>
        </div>
        <div className="kpi">
          <span>Receita/dia</span>
          <strong>{money(panel.total_revenue)}</strong>
        </div>
        <div className="kpi">
          <span>Lucro/dia</span>
          <strong>{money(panel.total_profit)}</strong>
        </div>
      </div>

      <h3>Composição do rebanho</h3>
      <Bars data={Object.entries(panel.by_situation)} />
      {panel.animals_without_lot > 0 && (
        <p className="hint">
          {integer.format(panel.animals_without_lot)} sem lote definido.
        </p>
      )}

      <h3>Comparativo por lote</h3>
      {panel.lots.length === 0 ? (
        <p>Nenhum lote com animais ou dieta.</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Lote</th>
                <th>Vacas</th>
                <th>Produção</th>
                <th>Custo</th>
                <th>Receita</th>
                <th>Lucro</th>
              </tr>
            </thead>
            <tbody>
              {panel.lots.map((lot) => (
                <tr key={lot.lote}>
                  <td>{lot.lote}</td>
                  <td>{integer.format(lot.animals)}</td>
                  <td>{decimal.format(lot.production)} L</td>
                  <td>{money(lot.feed_cost)}</td>
                  <td>{money(lot.revenue)}</td>
                  <td>{money(lot.profit)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <h3>Composição do custo de alimentação</h3>
      {panel.feed_breakdown.length === 0 ? (
        <p>Nenhum insumo cadastrado.</p>
      ) : (
        <Bars
          data={panel.feed_breakdown.map((item) => [item.name, item.total_cost])}
          format={(value) => currency.format(value)}
        />
      )}

      <h3>Estágio de lactação</h3>
      <Bars data={Object.entries(panel.lactation_stages)} />
      <p className="hint">
        Dias em lactação contados a partir do último parto registrado. Animais
        sem parto informado não entram nesta conta.
      </p>

      <h3>Maiores produções</h3>
      {panel.top_producers.length === 0 ? (
        <p>Sem leituras nesta data.</p>
      ) : (
        <Bars
          data={panel.top_producers.map((item) => [
            item.name ?? item.brinco ?? "—",
            item.production,
          ])}
          format={(value) => `${decimal.format(value)} L`}
        />
      )}

      <h3>Menores produções</h3>
      {panel.bottom_producers.length === 0 ? (
        <p>Sem leituras nesta data.</p>
      ) : (
        <Bars
          data={panel.bottom_producers.map((item) => [
            item.name ?? item.brinco ?? "—",
            item.production,
          ])}
          format={(value) => `${decimal.format(value)} L`}
        />
      )}
    </section>
  );
}
