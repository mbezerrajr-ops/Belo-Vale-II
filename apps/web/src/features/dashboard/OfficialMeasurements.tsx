import { useCallback, useEffect, useState } from "react";

import { getMeasurements } from "../../api/client";
import type { MeasurementRecord } from "../../api/types";

interface OfficialMeasurementsProps {
  farmId: string;
  token: string;
}

type LoadState = "loading" | "ready" | "error";

function totalLiters(records: MeasurementRecord[]): number {
  return records.reduce((sum, record) => {
    const raw = record.values.total;
    const parsed = typeof raw === "string" ? Number.parseFloat(raw) : Number(raw);
    return Number.isFinite(parsed) ? sum + parsed : sum;
  }, 0);
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
    const raw = record.values.total;
    const parsed = typeof raw === "string" ? Number.parseFloat(raw) : Number(raw);
    const liters = Number.isFinite(parsed) ? parsed : 0;
    const existing = byAnimal.get(record.animal_id);
    if (existing === undefined) {
      byAnimal.set(record.animal_id, {
        animalId: record.animal_id,
        label: record.animal_name ?? record.animal_identifier,
        measurementCount: 1,
        totalLiters: liters,
      });
    } else {
      existing.measurementCount += 1;
      existing.totalLiters += liters;
    }
  }
  return Array.from(byAnimal.values()).sort((a, b) => b.totalLiters - a.totalLiters);
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
    return <p>Carregando medições…</p>;
  }
  if (state === "error") {
    return <p role="alert">Não foi possível carregar as medições oficiais.</p>;
  }

  const byAnimal = totalsByAnimal(records);

  return (
    <section aria-label="Medições oficiais">
      <h2>Medições oficiais</h2>
      <button type="button" onClick={load}>
        Atualizar
      </button>
      <dl>
        <div>
          <dt>Medições ativas</dt>
          <dd>{records.length}</dd>
        </div>
        <div>
          <dt>Total no período (L)</dt>
          <dd>{totalLiters(records).toFixed(1)}</dd>
        </div>
      </dl>

      <h3>Por animal</h3>
      {byAnimal.length === 0 ? (
        <p>Nenhuma medição oficial ainda.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Animal</th>
              <th>Medições</th>
              <th>Total (L)</th>
            </tr>
          </thead>
          <tbody>
            {byAnimal.map((row) => (
              <tr key={row.animalId}>
                <td>{row.label}</td>
                <td>{row.measurementCount}</td>
                <td>{row.totalLiters.toFixed(1)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h3>Histórico recente</h3>
      {records.length === 0 ? (
        <p>Nenhuma medição oficial ainda.</p>
      ) : (
        <ul>
          {records.map((record) => (
            <li key={record.id}>
              {record.measured_on} — {record.animal_name ?? record.animal_identifier} —{" "}
              {String(record.values.total ?? "—")} L
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
