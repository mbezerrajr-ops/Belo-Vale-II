import { useEffect, useRef, useState } from 'react';
import { getMonthlyReport, downloadMonthlyReport } from '../../api/client';
import type { MonthlyReport, MonthlyResult } from '../../api/types';
import { apiMessage } from '../../auth/AccountEntry';
import { farmToday, brDate } from '../../ui/dates';
import { PageHeader } from '../../ui/PageHeader';
import { AppLink } from '../../ui/AppLink';
import { BarList, ChartCard, Columns, TableView, fmt } from '../../ui/charts';

export const MONTH_STATUS: Record<MonthlyResult['status'], string> = {
  positive: 'Positivo (estimado)', negative: 'Negativo (estimado)', balanced: 'Equilibrado (estimado)', insufficient: 'Dados insuficientes',
};
const monthName = (month: string) => new Intl.DateTimeFormat('pt-BR', { month: 'short', year: 'numeric', timeZone: 'UTC' }).format(new Date(`${month}-01T12:00:00Z`));
const liters = (value: number | null) => value === null ? '—' : fmt.liters(value);
const percentage = (value: number | null) => value === null ? '—' : `${fmt.dec(value)}%`;

export function MonthlyReportPage({ token, canExport }: { token: string; canExport: boolean }): JSX.Element {
  const today = farmToday();
  const thisMonth = today.slice(0, 7);
  const [start, setStart] = useState(`${today.slice(0, 4)}-01`);
  const [end, setEnd] = useState(thisMonth);
  const [simulate, setSimulate] = useState(false);
  const [report, setReport] = useState<MonthlyReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const requestId = useRef(0);
  const count = (Number(end.slice(0, 4)) - Number(start.slice(0, 4))) * 12 + Number(end.slice(5)) - Number(start.slice(5)) + 1;
  const problem = !start || !end ? 'Escolha os meses inicial e final.' : start > end ? 'O mês final deve ser igual ou posterior ao inicial.' : count > 24 ? 'Consulte até 24 meses por vez.' : end > thisMonth ? 'O mês final não pode estar no futuro.' : null;
  useEffect(() => {
    const id = ++requestId.current;
    setNotice(null); setError(null);
    if (problem) { setBusy(false); return; }
    setBusy(true);
    void getMonthlyReport(token, start, end, simulate).then(result => {
      if (id === requestId.current) setReport(result);
    }).catch(caught => { if (id === requestId.current) setError(apiMessage(caught)); }).finally(() => { if (id === requestId.current) setBusy(false); });
    return () => { requestId.current++; };
  }, [token, start, end, simulate, problem, reload]);
  const current = report?.months.find(row => row.in_progress);
  const stale = Boolean(report && (report.start_month !== start || report.end_month !== end || report.current_values_simulation !== simulate));
  async function exportReport(): Promise<void> {
    if (!report || busy || problem || stale) return;
    setExporting(true); setError(null); setNotice(null);
    try { await downloadMonthlyReport(token, report.start_month, report.end_month, report.current_values_simulation); setNotice('Planilha mensal gerada. Confira o download no navegador.'); }
    catch (caught) { setError(apiMessage(caught)); }
    finally { setExporting(false); }
  }
  const valid = report?.months.filter(row => row.estimated_result !== null) ?? [];
  const production = report?.months.filter(row => row.estimated_liters !== null) ?? [];
  return <section className="monthly-report">
    <PageHeader title="Relatório mensal" actions={canExport && <button type="button" onClick={() => void exportReport()} disabled={!report || busy || exporting || Boolean(problem) || stale}>{exporting ? 'Gerando…' : 'Baixar relatório (XLSX)'}</button>}>
      Compare a produção e o resultado estimado após alimentação. Outros gastos da fazenda não estão incluídos.
    </PageHeader>
    <div className="filters monthly-filters">
      <div><label htmlFor="monthly-start">Mês inicial</label><input id="monthly-start" type="month" max={thisMonth} value={start} onChange={e => setStart(e.target.value)} /></div>
      <div><label htmlFor="monthly-end">Mês final</label><input id="monthly-end" type="month" max={thisMonth} value={end} onChange={e => setEnd(e.target.value)} /></div>
      <button type="button" className="secondary" onClick={() => { setStart(`${today.slice(0, 4)}-01`); setEnd(thisMonth); }}>Este ano</button>
    </div>
    <label className="monthly-simulation"><input type="checkbox" checked={simulate} onChange={e => setSimulate(e.target.checked)} /> Estimar meses sem histórico usando preços e dietas atuais</label>
    <p className="hint">Use essa opção somente para simular. Valores atuais não comprovam o custo ou o preço praticado em meses antigos.</p>
    {problem && <p role="alert">{problem}</p>}
    {busy && <p role="status">Atualizando o relatório mensal…</p>}
    {error && <p role="alert">{error} <button type="button" className="secondary" onClick={() => setReload(n => n + 1)}>Tentar novamente</button></p>}
    {notice && <p role="status">{notice}</p>}
    {report && <div aria-busy={busy} className={busy || stale ? 'monthly-pending' : undefined}>
      <p className="hint">Período exibido: {monthName(report.start_month)} a {monthName(report.end_month)} · gerado em {brDate(report.generated_on)}.</p>
      {stale && <p className="warning">Os dados abaixo são da última consulta concluída. Aguarde a atualização ou corrija o intervalo.</p>}
      {report.current_values_simulation && <p className="warning">Simulação habilitada: os meses indicam quantos dias utilizam valores atuais por falta de histórico.</p>}
      {current && <p className="notice">{monthName(current.month)} está em andamento: considera {current.elapsed_days} de {current.calendar_days} dias. Fica fora da escolha do melhor e do pior mês.</p>}
      <div className="monthly-overview">
        <article><span>Meses encerrados com saldo positivo</span><strong>{report.positive_months}</strong></article>
        <article><span>Meses encerrados com saldo negativo</span><strong>{report.negative_months}</strong></article>
        <article><span>Melhor resultado estimado</span><strong>{report.best_month ? monthName(report.best_month) : '—'}</strong></article>
        <article><span>Pior resultado estimado</span><strong>{report.worst_month ? monthName(report.worst_month) : '—'}</strong></article>
      </div>
      <p className="hint">{report.balanced_months} mês(es) encerrado(s) em equilíbrio · {report.insufficient_months} mês(es) com dados insuficientes. Os saldos são estimados após alimentação, não representam lucro líquido.</p>
      <details className="monthly-method"><summary>Como o relatório calcula as estimativas</summary><p>{report.method}</p><p>Uma coleta isolada é uma amostra. A estimativa não preenche animais ausentes e pode variar com a cobertura das coletas.</p><p>Informe a vigência dos preços e das dietas em <AppLink href="/insumos">Insumos</AppLink>. O histórico começa nas datas conhecidas; valores ausentes não viram zero.</p></details>
      <div className="grid2">
        <ChartCard title="Receita e alimentação estimadas por mês" description="Somente meses com base financeira suficiente. O saldo aparece abaixo de cada mês.">
          {valid.length ? <div className="monthly-finance-chart"><div style={{ minWidth: valid.length * 80 + 60 }}><Columns ariaLabel="Receita e alimentação estimadas por mês" series={['Receita estimada', 'Alimentação estimada']} groups={valid.map(row => ({ label: monthName(row.month), values: [row.estimated_revenue!, row.estimated_feed_cost!], note: { text: fmt.brl(row.estimated_result), sign: row.status === 'negative' ? 'neg' : row.status === 'positive' ? 'pos' : 'zero' } }))} /></div></div> : <p className="chart-empty">Ainda não há meses com dados suficientes para comparar o resultado.</p>}
          <TableView columns={['Mês', 'Receita estimada', 'Alimentação estimada', 'Saldo estimado']} rows={valid.map(row => [monthName(row.month), fmt.brl(row.estimated_revenue), fmt.brl(row.estimated_feed_cost), fmt.brl(row.estimated_result)])} />
        </ChartCard>
        <ChartCard title="Produção estimada no período de cada mês" description="Média dos dias de coleta × dias do período. O mês atual é parcial.">
          {production.length ? <BarList data={production.map(row => ({ label: monthName(row.month), value: row.estimated_liters!, series: 2 }))} format={fmt.liters} /> : <p className="chart-empty">Sem coletas no intervalo selecionado.</p>}
          <TableView columns={['Mês', 'Registrado', 'Estimado', 'Dias com coleta']} rows={report.months.map(row => [monthName(row.month), fmt.liters(row.recorded_liters), liters(row.estimated_liters), row.reading_days])} />
        </ChartCard>
      </div>
      <h3>Fechamento mês a mês</h3>
      <div className="monthly-months">{[...report.months].reverse().map(row => <article className="chart-card monthly-card" key={row.month}>
        <header><h4>{monthName(row.month)} {row.in_progress && <small>em andamento</small>}</h4><span className={`monthly-status ${row.status}`}>{MONTH_STATUS[row.status]}</span></header>
        <dl className="monthly-values">
          <div><dt>Litros registrados</dt><dd>{fmt.liters(row.recorded_liters)}</dd></div>
          <div><dt>Litros estimados no período</dt><dd>{liters(row.estimated_liters)}</dd></div>
          <div><dt>Média por dia de coleta</dt><dd>{liters(row.average_liters_per_collection)}</dd></div>
          <div><dt>Média por vaca por leitura</dt><dd>{liters(row.average_liters_per_animal_reading)}</dd></div>
          <div><dt>Receita estimada</dt><dd>{fmt.brl(row.estimated_revenue)}</dd></div>
          <div><dt>Alimentação estimada</dt><dd>{fmt.brl(row.estimated_feed_cost)}</dd></div>
          <div><dt>Saldo estimado após alimentação</dt><dd>{fmt.brl(row.estimated_result)}</dd></div>
          <div><dt>Margem estimada</dt><dd>{percentage(row.margin_pct)}</dd></div>
        </dl>
        <p className="hint">{row.reading_days} dia(s) com coleta · {row.reading_count} leituras · {row.animals_read} animais distintos · período de {row.elapsed_days} dias.</p>
        <p className="hint">Variação da produção estimada frente ao mês anterior: {percentage(row.production_change_pct)} · diferença do saldo: {fmt.brl(row.result_change)}. Meses parciais e coberturas diferentes exigem cautela na comparação.</p>
        <details><summary>Base de cálculo e avisos de {monthName(row.month)}</summary>
          <p>Preço do leite conhecido ou simulado: {row.milk_price_days}/{row.elapsed_days} dias. Alimentação com base suficiente: {row.diet_days}/{row.elapsed_days} dias. Valores atuais simulados: {row.assumed_days} dias.</p>
          {row.animals_per_collection_min !== null && <p>Animais por dia de coleta: de {row.animals_per_collection_min} a {row.animals_per_collection_max}.</p>}
          {row.warnings.length ? <ul>{row.warnings.map(warning => <li key={warning}>{warning}</li>)}</ul> : <p>Há coletas em todos os dias do período e base financeira disponível. Os custos continuam sendo uma estimativa das dietas cadastradas.</p>}
        </details>
      </article>)}</div>
    </div>}
  </section>;
}
