/**
 * Datas no relógio de quem está usando.
 *
 * `new Date().toISOString()` devolve o dia em UTC: depois das 21h no Nordeste
 * já é "amanhã", e a API recusa coleta ou baixa com data no futuro. Por isso
 * o "hoje" é montado com os campos locais.
 */

export function localToday(now: Date = new Date()): string {
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
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
