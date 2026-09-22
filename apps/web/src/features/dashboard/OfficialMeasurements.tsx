import { useCallback, useEffect, useState } from "react";

import { getMeasurements } from "../../api/client";
import type { MeasurementRecord } from "../../api/types";
import { BarList, ChartCard, StatTile, TableView, fmt } from "../../ui/charts";
import { Icons } from "../../ui/Brand";
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
  const [records, setRecords] = useState<MeasurementRecord[]>([]);
  const [state, setState] = useState<LoadState>("loading");

  const load = useCallback(async (): Promise<void> => {
    setState("loading");
    try {
      const result = await getMeasurements({ farmId }, token);
      setRecords(result);
      setState("ready");
    } catch {
      setState("error");
    }
  }, [farmId, token]);

  useEffect(() => {
    load();
  }, [load]);

  if (state === "loading") {
    return (
      <section aria-label="Medições oficiais">
        <PageHeader title="Medições oficiais" />
        <div className="skeleton skeleton-card" />
      </section>
    );
  }
  if (state === "error") {
    return <p role="alert">Não foi possível carregar as medições oficiais.</p>;
  }

  const byAnimal = totalsByAnimal(records);
  const recent = [...records]
    .sort((a, b) => (a.measured_on < b.measured_on ? 1 : -1))
    .slice(0, 30);

  return (
    <section aria-label="Medições oficiais">
      <PageHeader
        title="Medições oficiais"
        actions={
          <button type="button" className="link-btn" onClick={load}>
            <Icons.atualizar /> Atualizar
          </button>
        }
      >
        Só entram aqui leituras aprovadas por uma pessoa ou migradas da baseline.
      </PageHeader>

      {/* Três indicadores: no celular o total ocupa a linha, e os outros
          dois dividem a de baixo — em vez de um ficar sozinho. */}
      <div className="kpis kpis-trio">
        <StatTile
          index={0}
          label="Total no período"
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

      <ChartCard title="Histórico recente" index={2}>
        {recent.length === 0 ? (
          <p className="chart-empty">Nenhuma medição oficial ainda.</p>
        ) : (
          <div className="table-wrap">
            <table>
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
                    <td className="num">{fmt.dec(liters(record))}</td>
                    <td className="muted">{record.reviewed_by ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </ChartCard>
    </section>
  );
}
