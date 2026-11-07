import { AppLink } from '../../ui/AppLink';
import { useState } from 'react';
import { setSupplyDiet } from '../../api/client';
import type { Supply } from '../../api/types';
import { apiMessage } from '../../auth/AccountEntry';
import { useActiveFarm } from '../workspace/context';
import { fmt } from '../../ui/charts';

export function SupplyDietForm({ supply, token, onSaved, onCancel }: { supply: Supply; token: string; onSaved: () => void; onCancel: () => void }): JSX.Element {
  const farm = useActiveFarm();
  const lots = (farm?.lot_settings ?? []).filter(lot => lot.kind === 'diet');
  const [lote, setLote] = useState(lots[0]?.name ?? '');
  const current = (name: string) => supply.diets.find(diet => diet.lote === name)?.kg_per_day;
  const [kg, setKg] = useState(String(current(lote) ?? ''));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const id = `diet-${supply.id}`;
  return <form className="supply-price" onSubmit={event => {
    event.preventDefault(); setBusy(true); setError(null);
    void setSupplyDiet(token, supply.id, lote, Number(kg)).then(onSaved).catch(caught => setError(apiMessage(caught))).finally(() => setBusy(false));
  }}>
    <h4>Dieta — {supply.name}</h4>
    {lots.length === 0 ? <p>Cadastre um lote de ordenha antes de definir a dieta. {farm?.role === 'admin' ? <AppLink href="/minha-conta/fazenda">Configurar minha fazenda</AppLink> : 'Peça ao administrador da fazenda.'}</p> : <>
      <label htmlFor={`${id}-lot`}>Lote de ordenha</label>
      <select id={`${id}-lot`} value={lote} onChange={event => { setLote(event.target.value); setKg(String(current(event.target.value) ?? '')); setError(null); }}>{lots.map(lot => <option key={lot.name}>{lot.name}</option>)}</select>
      <label htmlFor={`${id}-kg`}>Quantidade diária para o lote inteiro (kg)</label>
      <input id={`${id}-kg`} type="number" inputMode="decimal" min="0" step="0.001" required value={kg} onChange={e => setKg(e.target.value)} />
      <p className="hint">Some o consumo de todos os animais do lote. Use 0 se este insumo não faz parte da dieta.</p>
      {kg !== '' && Number.isFinite(Number(kg)) && <p>Este insumo custará <strong>{fmt.brl(Number(kg) * supply.price_per_kg)} por dia</strong> para {lote}.</p>}
      <p className="hint">Salvar atualiza a dieta usada no painel da fazenda.</p>
    </>}
    {error && <p role="alert">{error}</p>}
    <div className="ux-actions">{lots.length > 0 && <button disabled={busy || kg === ''}>{busy ? 'Salvando…' : 'Salvar dieta'}</button>}<button type="button" className="secondary" disabled={busy} onClick={onCancel}>Cancelar</button></div>
  </form>;
}
