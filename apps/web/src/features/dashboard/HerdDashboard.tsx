import { useEffect, useState } from "react";

import { getDashboard } from "../../api/client";
import type { DashboardFilters, DashboardSummary } from "../../api/types";
import {
  BarList,
  ChartCard,
  Columns,
  Donut,
  Sparkline,
  StatTile,
  TableView,
  fmt,
} from "../../ui/charts";
import { PageHeader } from "../../ui/PageHeader";

/**
 * Painel do rebanho.
 *
 * Porta os indicadores da plataforma legada sobre os dados no banco, com as
 * mesmas fórmulas. Cada gráfico tem tooltip por marca e visão em tabela.
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

function shortDate(iso: string): string {
  const [year, month, day] = iso.split("-");
  return `${day}/${month}/${year.slice(2)}`;
}

export function HerdDashboard({
  token,
  onLoad = getDashboard,
}: Props): JSX.Element {
  const [panel, setPanel] = useState<DashboardSummary | null>(null);
  const [filters, setFilters] = useState<DashboardFilters>({});
  const [error, setError] = useState<string | null>(null);
  // Trocar um filtro relê o painel: enquanto isso os números antigos ficam
  // esmaecidos, para ninguém ler o lote anterior como se fosse o escolhido.
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    onLoad(token, filters)
      .then((loaded) => {
        if (!cancelled) setPanel(loaded);
      })
      .catch((caught: unknown) => {
        const body = (caught as { body?: { detail?: string } })?.body;
        if (!cancelled) {
          setError(body?.detail ?? "Não foi possível carregar o painel.");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [token, filters, onLoad]);

  if (error) return <p role="alert">{error}</p>;
  if (panel === null) {
    return (
      <section className="dashboard">
        <PageHeader title="Painel do rebanho" />
        <div className="kpis">
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <div className="skeleton kpi" key={i} />
          ))}
        </div>
        <div className="skeleton skeleton-card" />
        <div className="skeleton skeleton-card" />
      </section>
    );
  }

  const lotNames = panel.lots.map((lot) => lot.lote);
  const partialCoverage =
    panel.measured_on !== null &&
    panel.animals_with_reading > 0 &&
    panel.animals_with_reading < panel.total_animals;

  const lotsWithData = panel.lots.filter((lot) => lot.animals > 0 || lot.feed_cost > 0);
  const lotsWithCost = lotsWithData.filter((lot) => lot.feed_cost > 0);
  // Topo comum das duas listas de produção (maiores e menores).
  const producerScale = Math.max(
    1,
    ...panel.top_producers.map((item) => item.production),
    ...panel.bottom_producers.map((item) => item.production),
  );

  return (
    <section className="dashboard" aria-busy={loading}>
      <PageHeader title="Painel do rebanho" />

      <div className="filters">
        <div>
          <label htmlFor="filtro-lote">Lote de ordenha</label>
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
                {shortDate(day)}
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

      {partialCoverage && (
        <p className="warning">
          Nesta data há leitura de {fmt.int(panel.animals_with_reading)} de{" "}
          {fmt.int(panel.total_animals)} animais. O custo mostrado é o do lote
          inteiro, então receita e lucro ficam subestimados — compare apenas
          datas com cobertura parecida.
        </p>
      )}

      <div className="kpis">
        <StatTile index={0} label="Animais" value={panel.total_animals} />
        <StatTile
          index={1}
          label="Com leitura"
          value={panel.animals_with_reading}
          hint={
            panel.total_animals > 0
              ? fmt.pct(panel.animals_with_reading / panel.total_animals) + " do rebanho"
              : undefined
          }
        />
        <StatTile
          index={2}
          label="Produção/dia"
          value={panel.total_production}
          format={fmt.liters}
          color="var(--series-3)"
        />
        <StatTile
          index={3}
          label="Custo/dia"
          value={panel.total_feed_cost}
          format={fmt.brl}
          color="var(--series-2)"
        />
        <StatTile
          index={4}
          label="Receita/dia"
          value={panel.total_revenue}
          format={fmt.brl}
          color="var(--series-1)"
        />
        <StatTile
          index={5}
          label="Lucro/dia"
          value={panel.total_profit}
          format={fmt.brl}
          color={
            panel.total_profit !== null && panel.total_profit < 0
              ? "var(--danger)"
              : "var(--good)"
          }
        />
      </div>

      <div className="grid2">
        <ChartCard
          index={0}
          title="Composição do rebanho"
          description={
            panel.animals_without_lot > 0
              ? `${fmt.int(panel.animals_without_lot)} fora de lote de ordenha.`
              : undefined
          }
        >
          <Donut
            centerLabel="animais"
            data={Object.entries(panel.by_situation).map(([label, value]) => ({
              label,
              value,
            }))}
          />
        </ChartCard>

        <ChartCard
          index={1}
          title="Produção por coleta"
          description="Total lido em cada data. A cobertura varia: compare datas parecidas."
        >
          <Sparkline
            points={panel.production_by_date.map((point) => ({
              label: shortDate(point.measured_on),
              value: point.liters,
            }))}
            format={fmt.liters}
          />
          <TableView
            columns={["Data", "Litros", "Animais lidos"]}
            rows={panel.production_by_date.map((point) => [
              shortDate(point.measured_on),
              fmt.dec(point.liters),
              point.animals,
            ])}
          />
        </ChartCard>
      </div>

      <ChartCard
        index={2}
        title="Comparativo por lote de ordenha"
        description="Custo da dieta e receita da produção lida, por dia. Abaixo de cada lote, o lucro."
      >
        {lotsWithCost.length === 0 ? (
          <p className="chart-empty">Nenhum lote com dieta cadastrada.</p>
        ) : (
          <Columns
            // Mesmas cores dos indicadores acima: receita verde, custo terracota.
            series={["Receita", "Custo"]}
            groups={lotsWithCost.map((lot) => ({
              label: lot.lote,
              values: [lot.revenue ?? 0, lot.feed_cost],
              note:
                lot.profit === null
                  ? undefined
                  : {
                      text: fmt.brl(lot.profit),
                      sign: lot.profit < 0 ? "neg" : lot.profit > 0 ? "pos" : "zero",
                    },
            }))}
          />
        )}
        <TableView
          columns={["Lote", "Vacas", "Produção", "Custo", "Receita", "Lucro"]}
          rows={lotsWithData.map((lot) => [
            lot.lote,
            lot.animals,
            fmt.liters(lot.production),
            fmt.brl(lot.feed_cost),
            fmt.brl(lot.revenue),
            fmt.brl(lot.profit),
          ])}
        />
      </ChartCard>

      {Object.keys(panel.by_management_group).length > 0 && (
        <ChartCard
          index={3}
          title="Onde os animais estão"
          description="Áreas e categorias da fazenda. Não são lotes de ordenha: não têm dieta nem custo."
        >
          <BarList
            // Os maiores grupos primeiro: é onde está a maior parte do rebanho.
            data={Object.entries(panel.by_management_group)
              .sort(([, a], [, b]) => b - a)
              .map(([label, value]) => ({
                label,
                value,
                series: 4,
              }))}
          />
        </ChartCard>
      )}

      <div className="grid2">
        <ChartCard
          index={4}
          title="Composição do custo de alimentação"
          description="Preço por quilo × dieta de cada lote, por dia."
        >
          {panel.feed_breakdown.length === 0 ? (
            <p className="chart-empty">Nenhum insumo cadastrado.</p>
          ) : (
            <BarList
              data={panel.feed_breakdown.map((item) => ({
                label: item.name,
                value: item.total_cost,
                series: 1,
              }))}
              format={fmt.brl}
            />
          )}
        </ChartCard>

        <ChartCard
          index={5}
          title="Estágio de lactação"
          description="Dias desde o último parto. Animais sem parto informado não entram."
        >
          <BarList
            data={Object.entries(panel.lactation_stages).map(([label, value]) => ({
              label,
              value,
            }))}
          />
        </ChartCard>
      </div>

      {/* As duas listas medem a mesma coisa: mesma cor e mesma escala. Com a
          escala de cada uma, 8,5 L aparecia com a barra quase cheia. */}
      <div className="grid2">
        <ChartCard index={6} title="Maiores produções" description="Nesta data de coleta.">
          {panel.top_producers.length === 0 ? (
            <p className="chart-empty">Sem leituras nesta data.</p>
          ) : (
            <BarList
              data={panel.top_producers.map((item) => ({
                label: item.name ?? item.brinco ?? "—",
                value: item.production,
                series: 2,
              }))}
              format={fmt.liters}
              tip={(d) => `${d.label}: ${fmt.liters(d.value)}`}
              max={producerScale}
            />
          )}
        </ChartCard>

        <ChartCard index={7} title="Menores produções" description="Nesta data de coleta.">
          {panel.bottom_producers.length === 0 ? (
            <p className="chart-empty">Sem leituras nesta data.</p>
          ) : (
            <BarList
              data={panel.bottom_producers.map((item) => ({
                label: item.name ?? item.brinco ?? "—",
                value: item.production,
                series: 2,
              }))}
              format={fmt.liters}
              tip={(d) => `${d.label}: ${fmt.liters(d.value)}`}
              max={producerScale}
            />
          )}
        </ChartCard>
      </div>
    </section>
  );
}
