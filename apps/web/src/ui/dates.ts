/**
 * Datas no relógio da fazenda.
 *
 * O servidor recusa coleta ou baixa com data no futuro comparando com o dia
 * da fazenda — UTC−3 fixo (`app/core/farm_clock.py`). O "hoje" das telas
 * precisa ser o mesmo, e não o do aparelho: um celular com outro fuso (ou o
 * CI, que roda em UTC) calcula "amanhã" das 21h à meia-noite de Brasília, e
 * o lançamento é recusado sem o funcionário entender por quê.
 */

/** Deslocamento fixo da fazenda, o mesmo do servidor. */
let selectedTimezone = "America/Recife";
export function setFarmTimezone(value: string): void { selectedTimezone = value; }

export function farmToday(now: Date = new Date()): string {
  const parts = new Intl.DateTimeFormat("en-CA", { timeZone: selectedTimezone, year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(now);
  const part = (name: string): string => parts.find((item) => item.type === name)?.value ?? "";
  return `${part("year")}-${part("month")}-${part("day")}`;
}

/** `2026-09-18` → `18/09/2026`. */
export function brDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const [year, month, day] = iso.slice(0, 10).split("-");
  return `${day}/${month}/${year}`;
}

/** Litros no formato do caderno: `21,5`. */
export function liters(value: number): string {
  return value.toLocaleString("pt-BR", { maximumFractionDigits: 2 });
}
