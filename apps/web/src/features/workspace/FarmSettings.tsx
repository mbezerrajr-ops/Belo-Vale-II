import { useState, type FormEvent } from "react";
import { workspaceRequest } from "../../api/client";
import { ApiError, type Farm } from "../../api/types";
import { apiMessage } from "../../auth/AccountEntry";

/** Configuração discreta da própria fazenda, dentro de Minha conta. */
export function FarmSettings({ token, farm, onSaved }: { token: string; farm: Farm; onSaved: (farm: Farm) => void }): JSX.Element {
  const [name, setName] = useState(farm.name);
  const [timezone, setTimezone] = useState(farm.timezone ?? "America/Recife");
  const [lots, setLots] = useState((farm.lot_settings ?? []).map((lot) => `${lot.kind === "diet" ? "ordenha" : "manejo"}: ${lot.name}`).join("\n"));
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function save(event: FormEvent): Promise<void> {
    event.preventDefault(); setBusy(true); setMessage(null); setError(null);
    try {
      const lot_settings = lots.split("\n").filter((line) => line.trim()).map((line) => {
        const match = /^(ordenha|manejo)\s*:\s*(.+)$/i.exec(line.trim());
        if (!match) throw new Error("Informe cada lote como ordenha: Nome ou manejo: Nome.");
        return { kind: match[1].toLowerCase() === "ordenha" ? "diet" : "management", name: match[2].trim() };
      });
      const saved = await workspaceRequest<Farm>("/farms/current", token, "PATCH", { name, timezone, lot_settings, milk_price_per_liter: farm.milk_price_per_liter ?? null });
      onSaved(saved); setMessage("Configuração da fazenda salva.");
    } catch (caught) { setError(caught instanceof Error && !(caught instanceof ApiError) ? caught.message : apiMessage(caught)); }
    finally { setBusy(false); }
  }

  return <details className="farm-settings">
    <summary>Configuração da minha fazenda</summary>
    <form onSubmit={(event) => void save(event)}>
      <label htmlFor="farm-name">Nome da fazenda</label><input id="farm-name" value={name} onChange={(event) => setName(event.target.value)} required maxLength={255} />
      <label htmlFor="farm-timezone">Fuso horário</label><input id="farm-timezone" value={timezone} onChange={(event) => setTimezone(event.target.value)} required placeholder="America/Sao_Paulo" />
      <label htmlFor="farm-lots">Lotes e grupos de manejo</label><textarea id="farm-lots" rows={5} value={lots} onChange={(event) => setLots(event.target.value)} placeholder={"ordenha: Lote principal\nmanejo: Bezerreiro"} />
      <p className="hint">Um por linha: ordenha: Nome ou manejo: Nome.</p>
      <button disabled={busy}>{busy ? "Salvando…" : "Salvar configuração da fazenda"}</button>
      {message && <p role="status">{message}</p>}{error && <p role="alert">{error}</p>}
    </form>
  </details>;
}
