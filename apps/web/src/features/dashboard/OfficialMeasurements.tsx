import { useCallback, useEffect, useRef, useState } from "react";

import { getMeasurements } from "../../api/client";
import type { MeasurementRecord } from "../../api/types";
import { BarList, ChartCard, StatTile, TableView, fmt } from "../../ui/charts";
import { Icons } from "../../ui/Brand";
import { farmToday } from '../../ui/dates';
import { PageHeader } from "../../ui/PageHeader";

interface OfficialMeasurementsProps {
  farmId: string;
  token: string;
}

type LoadState = "loading" | "ready" | "error";

/** A baseline grava `producao`; o pipeline de OCR grava `total`. */
function liters(record: MeasurementRecord): number {
  for (const key of ["total", "producao"]) {
    const raw = record.values[key];
    const parsed = typeof raw === "string" ? Number.parseFloat(raw) : Number(raw);
    if (Number.isFinite(parsed)) return parsed;
  }
  return 0;
}

function totalLiters(records: MeasurementRecord[]): number {
  return records.reduce((sum, record) => sum + liters(record), 0);
}

interface AnimalTotal {
  animalId: string;
  label: string;
  measurementCount: number;
  totalLiters: number;
}

function totalsByAnimal(records: MeasurementRecord[]): AnimalTotal[] {
  const byAnimal = new Map<string, AnimalTotal>();
  for (const record of records) {
    const value = liters(record);
    const existing = byAnimal.get(record.animal_id);
    if (existing === undefined) {
      byAnimal.set(record.animal_id, {
        animalId: record.animal_id,
        label: record.animal_name ?? record.animal_identifier,
        measurementCount: 1,
        totalLiters: value,
      });
    } else {
      existing.measurementCount += 1;
      existing.totalLiters += value;
    }
  }
  return Array.from(byAnimal.values()).sort((a, b) => b.totalLiters - a.totalLiters);
}

function br(iso: string): string {
  const [year, month, day] = iso.slice(0, 10).split("-");
  return `${day}/${month}/${year}`;
}

export function OfficialMeasurements({
  farmId,
  token,
}: OfficialMeasurementsProps): JSX.Element {
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [shown, setShown] = useState(30);
  const [loadedOnce, setLoadedOnce] = useState(false);
  const [applied, setApplied] = useState({ from: '', to: '' });
  const requestId = useRef(0);
  const [records, setRecords] = useState<MeasurementRecord[]>([]);
  const [state, setState] = useState<LoadState>("loading");

  const problem = Boolean(dateFrom && dateTo && dateFrom > dateTo);
  const load = useCallback(async (): Promise<void> => {
    const request = ++requestId.current;
    if (dateFrom && dateTo && dateFrom > dateTo) return;
    setState("loading");
    try {
      const result = await getMeasurements({ farmId, from: dateFrom || undefined, to: dateTo || undefined }, token);
      if (request !== requestId.current) return;
      setRecords(result); setShown(30); setApplied({ from: dateFrom, to: dateTo });
      setState("ready");
    } catch {
      if (request === requestId.current) setState("error");
    } finally { if (request === requestId.current) setLoadedOnce(true); }
  }, [farmId, token, dateFrom, dateTo]);

  useEffect(() => {
    load();
  }, [load]);

  if (state === "loading" && !loadedOnce) {
    return (
      <section aria-label="Histórico de produção">
        <PageHeader title="Histórico de produção" />
        <div className="skeleton skeleton-card" />
      </section>
    );
  }


  const byAnimal = totalsByAnimal(records);
  const recent = [...records]
    .sort((a, b) => (a.measured_on < b.measured_on ? 1 : -1))
    .slice(0, shown);

  return (
    <section aria-label="Histórico de produção">
      <PageHeader
        title="Histórico de produção"
        actions={
          <button type="button" className="link-btn icon-on-phone" aria-label="Atualizar" onClick={load}>
            <Icons.atualizar /> <span className="wide-only">Atualizar</span>
          </button>
        }
      >
        Consulte a produção já registrada. Fotos e áudios ainda aguardando conferência ficam em Revisão.
      </PageHeader>

      <div className="filters">
        <div><label htmlFor="history-from">De</label><input id="history-from" type="date" max={farmToday()} value={dateFrom} onChange={e => setDateFrom(e.target.value)} /></div>
        <div><label htmlFor="history-to">Até</label><input id="history-to" type="date" max={farmToday()} value={dateTo} onChange={e => setDateTo(e.target.value)} /></div>
        <button type="button" className="secondary" onClick={() => { setDateFrom(''); setDateTo(''); }}>Todo o histórico</button>
      </div>
      {problem && <p role="alert">A data final deve ser igual ou posterior à inicial. Os números abaixo ainda são da última consulta válida.</p>}
      <p className="hint" role="status">{applied.from || applied.to ? `Período consultado: ${applied.from ? br(applied.from) : 'primeiro registro'} até ${applied.to ? br(applied.to) : 'último registro'}.` : 'Período consultado: todo o histórico disponível.'}</p>
      {state === 'loading' && <p role="status">Atualizando o período…</p>}
      {state === 'error' && <p role="alert">Não foi possível atualizar o histórico. Os números continuam sendo da última consulta concluída. <button type="button" onClick={() => void load()}>Tentar novamente</button></p>}
      <div aria-busy={state === 'loading'}>
      {/* Três indicadores: no celular o total ocupa a linha, e os outros
          dois dividem a de baixo — em vez de um ficar sozinho. */}
      <div className="kpis kpis-trio">
        <StatTile
          index={0}
          label={applied.from || applied.to ? "Total no período consultado" : "Total de todo o histórico"}
          value={totalLiters(records)}
          format={fmt.liters}
          color="var(--series-3)"
        />
        <StatTile index={1} label="Medições ativas" value={records.length} />
        <StatTile index={2} label="Animais medidos" value={byAnimal.length} />
      </div>

      <ChartCard title="Maiores totais por animal" index={1}>
        {byAnimal.length === 0 ? (
          <p className="chart-empty">Nenhuma medição oficial ainda.</p>
        ) : (
          <BarList
            data={byAnimal.slice(0, 12).map((row) => ({
              label: row.label,
              value: row.totalLiters,
              series: 2,
            }))}
            format={fmt.liters}
          />
        )}
        <TableView
          columns={["Animal", "Medições", "Total (L)"]}
          rows={byAnimal.map((row) => [
            row.label,
            row.measurementCount,
            fmt.dec(row.totalLiters),
          ])}
        />
      </ChartCard>

      <ChartCard title={`Registros: ${recent.length} de ${records.length} · mais recentes primeiro`} index={2}>
        {recent.length === 0 ? (
          <p className="chart-empty">Nenhuma medição oficial ainda.</p>
        ) : (
          <div className="table-wrap">
            <table className="stack-on-phone">
              <thead>
                <tr>
                  <th>Data</th>
                  <th>Animal</th>
                  <th className="num">Litros</th>
                  <th>Conferido por</th>
                </tr>
              </thead>
              <tbody>
                {recent.map((record) => (
                  <tr key={record.id}>
                    <td>{br(record.measured_on)}</td>
                    <td>{record.animal_name ?? record.animal_identifier}</td>
                    <td className="num">{fmt.dec(liters(record))} L</td>
                    <td className="muted">{record.reviewed_by ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </ChartCard>
      {shown < records.length && <button type="button" className="secondary" onClick={() => setShown(n => n + 30)}>Mostrar mais registros ({records.length - shown} restantes)</button>}
      </div>
    </section>
  );
}
