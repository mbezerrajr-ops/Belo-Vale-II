import { useRef, useState, type FormEvent } from 'react';
import { workspaceRequest } from '../../api/client';
import type { Farm } from '../../api/types';
import { apiMessage } from '../../auth/AccountEntry';

const zones = [
  ['America/Recife', 'Pernambuco, Paraíba, Alagoas e região'],
  ['America/Sao_Paulo', 'São Paulo, Brasília e região'],
  ['America/Bahia', 'Bahia'], ['America/Fortaleza', 'Ceará, Maranhão, Piauí e região'],
  ['America/Belem', 'Belém e região'], ['America/Manaus', 'Manaus e região'],
  ['America/Cuiaba', 'Mato Grosso'], ['America/Campo_Grande', 'Mato Grosso do Sul'],
  ['America/Porto_Velho', 'Rondônia'], ['America/Boa_Vista', 'Roraima'],
  ['America/Rio_Branco', 'Acre'], ['America/Noronha', 'Fernando de Noronha'],
];

export function FarmSettings({ token, farm, onSaved }: { token: string; farm: Farm; onSaved: (farm: Farm) => void }): JSX.Element {
  const [name, setName] = useState(farm.name);
  const [timezone, setTimezone] = useState(farm.timezone ?? 'America/Recife');
  const [lots, setLots] = useState((farm.lot_settings ?? []).map(lot => ({ ...lot, key: crypto.randomUUID() })));
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [removing, setRemoving] = useState<string | null>(null);
  const form = useRef<HTMLFormElement>(null);
  async function save(event: FormEvent): Promise<void> {
    event.preventDefault(); setMessage(null); setError(null);
    if (!name.trim()) { setError('Informe o nome da fazenda.'); form.current?.querySelector<HTMLElement>('#farm-name')?.focus(); return; }
    const blank = lots.find(lot => !lot.name.trim());
    if (blank) { setError('Informe o nome do destino ou remova a linha vazia.'); form.current?.querySelector<HTMLElement>(`#lot-name-${blank.key}`)?.focus(); return; }
    const normalized = lots.map(lot => lot.name.trim().toLocaleLowerCase());
    const repeated = normalized.findIndex((name, i) => normalized.indexOf(name) !== i);
    if (repeated >= 0) {
      setError('Já existe um lote ou grupo com esse nome. Use nomes diferentes.');
      form.current?.querySelector<HTMLElement>(`#lot-name-${lots[repeated].key}`)?.focus(); return;
    }
    setBusy(true);
    try {
      const saved = await workspaceRequest<Farm>('/farms/current', token, 'PATCH', {
        name: name.trim(), timezone,
        lot_settings: lots.map(({ name, kind }) => ({ name: name.trim(), kind })),
        milk_price_per_liter: farm.milk_price_per_liter ?? null,
      });
      onSaved(saved); setMessage('Configuração da fazenda salva.');
    } catch (caught) { setError(apiMessage(caught)); }
    finally { setBusy(false); }
  }
  return <details className="farm-settings" open={location.pathname.endsWith('/fazenda') || undefined}>
    <summary>Configuração da minha fazenda</summary>
    <form ref={form} onSubmit={event => void save(event)}>
      <label htmlFor="farm-name">Nome da fazenda</label>
      <input id="farm-name" value={name} onChange={e => setName(e.target.value)} required maxLength={255} />
      <label htmlFor="farm-timezone">Região e fuso horário</label>
      <select id="farm-timezone" value={timezone} onChange={e => setTimezone(e.target.value)}>
        {!zones.some(([value]) => value === timezone) && <option value={timezone}>Fuso atual: {timezone}</option>}
        {zones.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
      </select>
      <p className="hint">Escolha a região da propriedade. Ela define o dia usado nos registros.</p>
      <h3>Lotes e grupos de manejo</h3>
      <p className="hint">Lotes de ordenha agrupam a produção e a dieta. Grupos de manejo indicam áreas ou categorias, como Bezerreiro.</p>
      {lots.length === 0 && <p>Nenhum lote cadastrado. Adicione o primeiro para organizar seus animais.</p>}
      {lots.map((lot, index) => <fieldset className="farm-lot-row" key={lot.key}>
        <legend>Destino {index + 1}</legend>
        <label htmlFor={`lot-name-${lot.key}`}>Nome</label>
        <input id={`lot-name-${lot.key}`} value={lot.name} maxLength={64} required onChange={e => setLots(rows => rows.map(row => row.key === lot.key ? { ...row, name: e.target.value } : row))} />
        <label htmlFor={`lot-kind-${lot.key}`}>Tipo</label>
        <select id={`lot-kind-${lot.key}`} value={lot.kind} onChange={e => setLots(rows => rows.map(row => row.key === lot.key ? { ...row, kind: e.target.value as 'diet' | 'management' } : row))}>
          <option value="diet">Lote de ordenha</option><option value="management">Grupo de manejo</option>
        </select>
        {removing === lot.key ? <div className="notice">
          <p>Remover “{lot.name || 'destino sem nome'}” da configuração? A alteração só será salva ao confirmar a configuração.</p>
          <div className="ux-actions"><button type="button" className="secondary danger" onClick={() => { setLots(rows => rows.filter(row => row.key !== lot.key)); setRemoving(null); }}>Remover da lista</button><button type="button" className="secondary" onClick={() => setRemoving(null)}>Manter destino</button></div>
        </div> : <button type="button" className="link-btn danger" onClick={() => setRemoving(lot.key)}>Remover {lot.name || 'destino'}</button>}
      </fieldset>)}
      <button type="button" className="secondary" onClick={() => setLots(rows => [...rows, { key: crypto.randomUUID(), name: '', kind: 'diet' }])}>Adicionar lote ou grupo</button>
      <p className="hint">Destinos com animais em uso não podem ser removidos nem mudar de tipo.</p>
      <div className="ux-actions"><button disabled={busy}>{busy ? 'Salvando…' : 'Salvar configuração da fazenda'}</button><button type="button" className="secondary" disabled={busy} onClick={() => { setName(farm.name); setTimezone(farm.timezone ?? 'America/Recife'); setLots((farm.lot_settings ?? []).map(lot => ({ ...lot, key: crypto.randomUUID() }))); setError(null); setMessage(null); setRemoving(null); }}>Descartar alterações</button></div>
      {message && <p role="status">{message}</p>}{error && <p role="alert">{error}</p>}
    </form>
  </details>;
}
