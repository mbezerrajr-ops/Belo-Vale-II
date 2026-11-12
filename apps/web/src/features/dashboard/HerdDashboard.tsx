import { AppLink } from '../../ui/AppLink';
import { useEffect, useState } from "react";

import { useActiveFarm } from '../workspace/context';
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
 * Quando falta o preço do leite, receita e resultado após alimentação aparecem como "—", nunca como
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

/** Junta as opções já vistas às que chegaram, em ordem natural (LOTE 2 antes de LOTE 10). */
function mergeOptions(current: string[], seen: string[]): string[] {
  const next = Array.from(new Set([...current, ...seen]));
  next.sort((a, b) => a.localeCompare(b, "pt-BR", { numeric: true }));
  return next.length === current.length ? current : next;
}

function shortDate(iso: string): string {
  const [year, month, day] = iso.split("-");
  return `${day}/${month}/${year.slice(2)}`;
}

export function HerdDashboard({
  token,
  onLoad = getDashboard,
}: Props): JSX.Element {
  const farm = useActiveFarm();
  const [panel, setPanel] = useState<DashboardSummary | null>(null);
  const [filters, setFilters] = useState<DashboardFilters>({});
  const [error, setError] = useState<string | null>(null);
  // Trocar um filtro relê o painel: enquanto isso os números antigos ficam
  // esmaecidos, para ninguém ler o lote anterior como se fosse o escolhido.
  const [loading, setLoading] = useState(true);
  // Muda no "Tentar de novo", para carregar outra vez com os mesmos filtros.
  const [attempt, setAttempt] = useState(0);
  // Maiores e menores produções dividem um cartão: medem a mesma coisa.
  const [ranking, setRanking] = useState<"maiores" | "menores">("maiores");
  // As opções dos filtros não podem vir só do painel filtrado: com LOTE 2
  // escolhido, o servidor devolve só o LOTE 2, e a lista encolhia para
  // "Todos" e ele — para trocar de lote era preciso voltar a Todos antes.
  // Guarda tudo o que já apareceu.
  const [lotOptions, setLotOptions] = useState<string[]>([]);
  const [situationOptions, setSituationOptions] = useState<string[]>([]);
  useEffect(() => {
    if (panel === null) return;
    setLotOptions((current) => mergeOptions(current, panel.lots.map((lot) => lot.lote)));
    setSituationOptions((current) => mergeOptions(current, Object.keys(panel.by_situation)));
  }, [panel]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    // Cada carregamento começa limpo: um erro de antes (o sinal que caiu)
    // não pode prender a tela depois que o sinal volta.
    setError(null);
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
  }, [token, filters, onLoad, attempt]);

  if (error) {
    return (
      <section className="dashboard">
        <p role="alert">{error}</p>
        <button type="button" onClick={() => setAttempt((count) => count + 1)}>
          Tentar de novo
        </button>
      </section>
    );
  }
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

  const lotNames = mergeOptions(lotOptions, panel.lots.map((lot) => lot.lote));
  const situationNames = mergeOptions(situationOptions, Object.keys(panel.by_situation));
  // Só os lotes de ordenha contam: é deles o custo de dieta. Seca fora de
  // lote não tem custo, e contá-la faria o aviso aparecer em toda data.
  const partialCoverage =
    panel.measured_on !== null &&
    panel.lot_animals_with_reading > 0 &&
    panel.lot_animals_with_reading < panel.lot_animals;

  const missingDiets = panel.missing_diet_lots ?? [];
  const costIncomplete = missingDiets.length > 0 || panel.lots.length === 0;
  const lotsWithData = panel.lots.filter((lot) => lot.animals > 0 || lot.feed_cost > 0);
  const lotsWithCost = lotsWithData.filter((lot) => !missingDiets.includes(lot.lote));
  // Topo comum das duas listas de produção (maiores e menores).
  const producerScale = Math.max(
    1,
    ...panel.top_producers.map((item) => item.production),
    ...panel.bottom_producers.map((item) => item.production),
  );

  return (
    <section className="dashboard" aria-busy={loading}>
      <PageHeader title="Painel do rebanho" actions={<AppLink className="link-btn" href="/relatorios">Relatório mensal</AppLink>} />
      {panel.total_animals === 0 && <section className="ux-first-steps" aria-labelledby="first-steps-title">
        <h3 id="first-steps-title">Vamos começar sua fazenda</h3>
        <p>Prepare o cadastro e depois registre a primeira produção.</p>
        <ol>
          <li>{farm?.role === 'admin' ? <AppLink href="/minha-conta/fazenda">Configurar os lotes da fazenda</AppLink> : 'Peça ao administrador para configurar os lotes.'}</li>
          <li><AppLink href="/animais">Cadastrar os animais</AppLink></li>
          <li><AppLink href="/producao">Lançar a produção</AppLink> ou <AppLink href="/revisao/foto">ler uma foto da folha</AppLink></li>
        </ol>
        <p className="hint">Depois, em Insumos, informe os preços e as dietas para acompanhar o custo de alimentação.</p>
      </section>}

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
            {situationNames.map((name) => (
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
          Nenhuma produção registrada ainda. Cadastre os animais e lance a produção ou envie uma foto da folha para leitura.
        </p>
      )}

      {panel.milk_price === null && (
        <p className="warning">
          Preço do leite não definido — receita e resultado após alimentação não podem ser
          calculados. Ajuste em Insumos.
        </p>
      )}

      {partialCoverage && (
        // O custo é o do lote inteiro e a receita só das vacas lidas: com
        // pouca leitura, o lucro sai baixo. Uma linha, sem esconder isso.
        <p className="warning coverage">
          Leitura de {fmt.int(panel.lot_animals_with_reading)} de {fmt.int(panel.lot_animals)}{" "}
          animais dos lotes de ordenha (
          {fmt.pct(panel.lot_animals_with_reading / panel.lot_animals)}) — receita e resultado após alimentação saem
          subestimados; compare datas com cobertura parecida.
        </p>
      )}

      <p className="hint">O resultado considera a receita do leite menos a alimentação cadastrada. Outros gastos da fazenda, como mão de obra e energia, não estão incluídos.</p>
      {costIncomplete && <p className="warning"><span>{missingDiets.length > 0 ? `Dieta não cadastrada: ${missingDiets.join(', ')}.` : 'Ainda não há base para calcular o custo de alimentação.'} O custo e o resultado ficam incompletos. <AppLink href="/insumos">Definir dietas em Insumos</AppLink>.</span></p>}
      {/* O que o dono quer saber primeiro: quanto saiu de leite e quanto
          sobrou. O resto explica esses dois. */}
      <div className="kpis kpis-hero">
        <StatTile
          index={0}
          size="hero"
          label="Produção/dia"
          value={panel.total_production}
          format={fmt.liters}
          color="var(--series-3)"
        />
        <StatTile
          index={1}
          size="hero"
          label="Resultado após alimentação/dia"
          value={costIncomplete ? null : panel.total_profit}
          format={fmt.brl}
          color={
            panel.total_profit !== null && panel.total_profit < 0
              ? "var(--danger)"
              : "var(--good)"
          }
        />
      </div>
      <div className="kpis kpis-trio">
        <StatTile
          index={2}
          label="Receita/dia"
          value={panel.total_revenue}
          format={fmt.brl}
          color="var(--series-1)"
        />
        <StatTile
          index={3}
          label="Alimentação/dia"
          value={costIncomplete ? null : panel.total_feed_cost}
          format={fmt.brl}
          color="var(--series-2)"
        />
        <StatTile
          index={4}
          label="Animais"
          value={panel.total_animals}
          hint={`${fmt.int(panel.animals_with_reading)} com leitura`}
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
        description="Custo da dieta e receita da produção lida, por dia. Abaixo de cada lote, o resultado após alimentação."
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
                      text: missingDiets.includes(lot.lote) ? "Incompleto" : fmt.brl(lot.profit),
                      sign: lot.profit < 0 ? "neg" : lot.profit > 0 ? "pos" : "zero",
                    },
            }))}
          />
        )}
        <TableView
          columns={["Lote", "Vacas", "Produção", "Alimentação", "Receita", "Resultado após alimentação"]}
          rows={lotsWithData.map((lot) => [
            lot.lote,
            lot.animals,
            fmt.liters(lot.production),
            missingDiets.includes(lot.lote) ? "Dieta não cadastrada" : fmt.brl(lot.feed_cost),
            fmt.brl(lot.revenue),
            missingDiets.includes(lot.lote) ? "Incompleto" : fmt.brl(lot.profit),
          ])}
        />
      </ChartCard>

      {Object.keys(panel.by_management_group).length > 0 && (
        <ChartCard
          index={3}
          title="Onde os animais estão"
          description="Áreas e categorias da fazenda. Não são lotes de ordenha: não possuem dieta de ordenha neste cálculo."
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

      {/* As duas listas medem a mesma coisa: um cartão, mesma cor e mesma
          escala. Com a escala de cada uma, 8,5 L aparecia com a barra quase
          cheia. */}
      <ChartCard
        index={6}
        title="Produção por vaca"
        description="Nesta data de coleta."
        aside={
          <div className="segmented" role="group" aria-label="Quais vacas">
            <button
              type="button"
              aria-pressed={ranking === "maiores"}
              onClick={() => setRanking("maiores")}
            >
              Maiores
            </button>
            <button
              type="button"
              aria-pressed={ranking === "menores"}
              onClick={() => setRanking("menores")}
            >
              Menores
            </button>
          </div>
        }
      >
        {(() => {
          const list = ranking === "maiores" ? panel.top_producers : panel.bottom_producers;
          return list.length === 0 ? (
            <p className="chart-empty">Sem leituras nesta data.</p>
          ) : (
            <BarList
              data={list.map((item) => ({
                label: item.name ?? item.brinco ?? "—",
                value: item.production,
                series: 2,
              }))}
              format={fmt.liters}
              tip={(d) => `${d.label}: ${fmt.liters(d.value)}`}
              max={producerScale}
            />
          );
        })()}
      </ChartCard>
    </section>
  );
}
