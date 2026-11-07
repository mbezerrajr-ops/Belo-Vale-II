import { AppLink } from '../../ui/AppLink';
import { useActiveFarm } from './context';

export function FarmLotSelect({ id, value, onChange, optional = false }: {
  id: string; value: string; onChange: (value: string) => void; optional?: boolean;
}): JSX.Element {
  const farm = useActiveFarm();
  const lots = farm?.lot_settings ?? [];
  return <>
    <select id={id} value={value} onChange={event => onChange(event.target.value)} required={!optional} disabled={lots.length === 0}>
      <option value="">{optional ? 'Sem lote ou grupo por enquanto' : 'Selecione o destino'}</option>
      {(['diet', 'management'] as const).map(kind => <optgroup key={kind} label={kind === 'diet' ? 'Lotes de ordenha' : 'Grupos de manejo'}>
        {lots.filter(lot => lot.kind === kind).map(lot => <option key={lot.name} value={lot.name}>{lot.name}</option>)}
      </optgroup>)}
    </select>
    {lots.length === 0 && <p className="hint">Ainda não há lotes ou grupos configurados. {farm?.role === 'admin' ? <AppLink href="/minha-conta/fazenda">Configurar minha fazenda</AppLink> : 'Peça ao administrador para cadastrar os destinos.'}</p>}
  </>;
}
