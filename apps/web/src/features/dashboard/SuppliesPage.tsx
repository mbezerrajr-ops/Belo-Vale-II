import { SupplyDietForm } from './SupplyDietForm';
import { useEffect, useState, type CSSProperties } from "react";

import {
  createSupply,
  getCurrentFarm,
  getSupplyPrices,
  listSupplies,
  setMilkPrice,
  updateSupplyPrice,
} from "../../api/client";
import type { Supply, SupplyPrice } from "../../api/types";
import { brDate, farmToday } from "../../ui/dates";
import { Icons } from "../../ui/Brand";
import { BarList, TableView, fmt } from "../../ui/charts";
import { PageHeader } from "../../ui/PageHeader";
import { apiMessage } from '../../auth/AccountEntry';

/**
 * Insumos e dieta.
 *
 * O preço de cada insumo e a dieta de cada lote são o que alimenta o cálculo
 * de custo do painel. Alterar o preço acrescenta ao histórico em vez de apagar
 * o anterior — isso é dito na tela, para o usuário não temer perder o registro.
 */

interface Props {
  token: string;
  canEdit: boolean;
  milkPrice?: number | null;
  /** O preço do leite foi salvo: quem guarda a fazenda atualiza o seu. */
  onMilkPriceSaved?: (pricePerLiter: number | null) => void;
  onList?: (token: string) => Promise<Supply[]>;
  onUpdatePrice?: (
    token: string,
    supplyId: string,
    pricePerKg: number,
    effectiveOn?: string,
  ) => Promise<Supply>;
  onCreate?: (token: string, name: string, pricePerKg: number) => Promise<Supply>;
  onSetMilkPrice?: (token: string, pricePerLiter: number, effectiveOn?: string) => Promise<void>;
  onLoadPrices?: (token: string, supplyId: string) => Promise<SupplyPrice[]>;
}

const precise = new Intl.NumberFormat("pt-BR", {
  style: "currency",
  currency: "BRL",
  minimumFractionDigits: 2,
  maximumFractionDigits: 4,
});

function errorMessage(error: unknown): string {
  const body = (error as { body?: { detail?: string } })?.body;
  return typeof body?.detail === 'string' ? body.detail : apiMessage(error);
}

export function SuppliesPage({
  token,
  canEdit,
  milkPrice = null,
  onList = listSupplies,
  onUpdatePrice = updateSupplyPrice,
  onCreate = createSupply,
  onSetMilkPrice = setMilkPrice,
  onLoadPrices = getSupplyPrices,
  onMilkPriceSaved,
}: Props): JSX.Element {
  const [supplies, setSupplies] = useState<Supply[] | null>(null);
  const [prices, setPrices] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [newName, setNewName] = useState("");
  const [newPrice, setNewPrice] = useState("");
  const [milk, setMilk] = useState(milkPrice === null ? "" : String(milkPrice));
  const [milkSaved, setMilkSaved] = useState<number | null>(null);
  // A fazenda chega junto com a tela: o preço em vigor entra no campo quando
  // chegar, em vez de o campo ficar vazio com o preço definido.
  useEffect(() => {
    setMilk(milkPrice === null ? "" : String(milkPrice));
  }, [milkPrice]);
  // Histórico aberto por insumo. Carregado só quando pedido.
  const [history, setHistory] = useState<Record<string, SupplyPrice[]>>({});
  // Um formulário de preço aberto por vez; fechados, cada insumo cabe numa
  // olhada — antes cada um ocupava quase uma tela do celular.
  const [editing, setEditing] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [milkSince, setMilkSince] = useState(farmToday());
  const [priceSince, setPriceSince] = useState(farmToday());
  const [dietEditor, setDietEditor] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function toggleHistory(supplyId: string): Promise<void> {
    if (history[supplyId]) {
      const { [supplyId]: _closed, ...rest } = history;
      setHistory(rest);
      return;
    }
    try {
      const prices = await onLoadPrices(token, supplyId);
      setHistory((current) => ({ ...current, [supplyId]: prices }));
    } catch (caught) {
      setError(errorMessage(caught));
    }
  }

  async function reload(): Promise<void> {
    try {
      setSupplies(await onList(token));
    } catch (caught) {
      setError(errorMessage(caught));
    }
  }

  useEffect(() => {
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  async function guard(action: () => Promise<unknown>): Promise<void> {
    setBusy(true);
    setError(null);
    try {
      await action();
      await reload();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="supplies">
      <PageHeader
        title="Insumos e dieta"
        actions={
          canEdit && (
            <button
              type="button"
              className="secondary"
              aria-expanded={creating}
              onClick={() => setCreating((open) => !open)}
            >
              <Icons.novo /> Novo insumo
            </button>
          )
        }
      >
        Preço do insumo × dieta do lote = o custo diário que aparece no painel.
      </PageHeader>

      {error && <p role="alert">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      {supplies?.length === 0 && <p className="notice">Comece cadastrando um insumo. Depois informe quanto o lote inteiro consome por dia para calcular o custo de alimentação.</p>}

      {canEdit && creating && (
        <form
          className="new-supply"
          onSubmit={(event) => {
            event.preventDefault();
            void guard(async () => {
              await onCreate(token, newName.trim(), Number(newPrice));
              setCreating(false);
              setNewName("");
              setNewPrice("");
            });
          }}
        >
          <h3>Novo insumo</h3>
          <label htmlFor="new-supply-name">Nome</label>
          <input
            id="new-supply-name"
            value={newName}
            onChange={(event) => setNewName(event.target.value)}
            autoComplete="off"
          />
          <label htmlFor="new-supply-price">Preço por kg (R$)</label>
          <input
            id="new-supply-price"
            type="number"
            step="0.00001"
            min="0"
            inputMode="decimal"
            value={newPrice}
            onChange={(event) => setNewPrice(event.target.value)}
          />
          <button type="submit" disabled={busy || !newName.trim() || !newPrice}>
            Cadastrar insumo
          </button><button type="button" className="secondary" onClick={() => setCreating(false)}>Cancelar</button>
        </form>
      )}

      {canEdit && (
        <form
          className="milk-price"
          onSubmit={(event) => {
            event.preventDefault();
            const price = Number(milk);
            setMilkSaved(null);
            void guard(async () => {
              if (milkSince === farmToday()) await onSetMilkPrice(token, price);
              else await onSetMilkPrice(token, price, milkSince);
              setMilkSaved(price);
              if (milkSince === farmToday()) onMilkPriceSaved?.(price);
              else try {
                const current = await getCurrentFarm(token);
                setMilk(current.milk_price_per_liter == null ? '' : String(current.milk_price_per_liter));
                onMilkPriceSaved?.(current.milk_price_per_liter ?? null);
              } catch { setNotice('O preço foi registrado. Reabra a tela para conferir o valor atualmente em vigor.'); }
            });
          }}
        >
          <h3>Preço do leite</h3>
          <p className="hint">Base da receita do leite e do resultado após alimentação.</p>
          <label htmlFor="milk-price-since">Preço do leite válido a partir de</label>
          <input id="milk-price-since" type="date" max={farmToday()} required value={milkSince} onChange={e => setMilkSince(e.target.value)} />
          <p className="hint">Informe a vigência para preservar o fechamento dos meses anteriores.</p>
          <label htmlFor="milk-price">Preço por litro (R$)</label>
          <div className="inline-field">
            <input
              id="milk-price"
              type="number"
              step="0.01"
              min="0"
              inputMode="decimal"
              value={milk}
              onChange={(event) => setMilk(event.target.value)}
            />
            <button type="submit" disabled={busy || milk === ""}>
              Salvar preço do leite
            </button>
          </div>
          {milkSaved !== null && (
            <p role="status">
              Preço do leite salvo: R$ {milkSaved.toLocaleString("pt-BR", { minimumFractionDigits: 2 })}{" "}
              por litro, com vigência em {brDate(milkSince)}.
            </p>
          )}
        </form>
      )}

      {supplies === null ? (
        <div className="skeleton skeleton-card" />
      ) : (
        <ul className="supply-list">
          {supplies.map((item, index) => (
            <li key={item.id} style={{ "--i": index } as CSSProperties}>
              <header className="supply-head">
                <h3>{item.name}</h3>
                <p className="price">{precise.format(item.price_per_kg)} / kg</p>
                {item.diets.length > 0 && (
                  <p className="supply-total">
                    {fmt.brl(
                      item.diets.reduce((sum, diet) => sum + diet.kg_per_day, 0) *
                        item.price_per_kg,
                    )}{" "}
                    por dia
                  </p>
                )}
              </header>
              {history[item.id] && (
                <ul className="price-history" aria-label={`Preços de ${item.name}`}>
                  {history[item.id].map((price) => (
                    <li key={price.effective_on}>
                      <span>desde {brDate(price.effective_on)}</span>
                      <strong>{precise.format(price.price_per_kg)} / kg</strong>
                      <small>
                        {price.source === "legacy_baseline"
                          ? "sistema antigo"
                          : `registrado por ${price.recorded_by ?? "—"}`}
                      </small>
                    </li>
                  ))}
                </ul>
              )}

              {item.diets.length === 0 ? (
                <p className="chart-empty">Sem dieta cadastrada para este insumo.</p>
              ) : (
                <BarList
                  data={item.diets.map((diet) => ({
                    label: diet.lote,
                    value: diet.kg_per_day * item.price_per_kg,
                    series: 1,
                  }))}
                  format={fmt.brl}
                  tip={(d) => {
                    const diet = item.diets.find((entry) => entry.lote === d.label);
                    return `${d.label}: ${diet?.kg_per_day ?? 0} kg/dia · ${fmt.brl(d.value)}/dia`;
                  }}
                />
              )}

              {item.diets.length > 0 && (
                <TableView
                  columns={["Lote", "kg/dia do lote inteiro", "Custo de alimentação/dia"]}
                  rows={item.diets.map((diet) => [
                    diet.lote,
                    diet.kg_per_day,
                    fmt.brl(diet.kg_per_day * item.price_per_kg),
                  ])}
                />
              )}

              {dietEditor === item.id && <SupplyDietForm supply={item} token={token} onCancel={() => setDietEditor(null)} onSaved={() => { setDietEditor(null); setNotice(`Dieta de ${item.name} salva. O painel usa a vigência mais recente.`); void reload(); }} />}
              <div className="supply-actions">
                {canEdit && <button type="button" className="secondary" aria-expanded={dietEditor === item.id} onClick={() => { setDietEditor(item.id); setEditing(null); setNotice(null); }}>Definir dieta</button>}
                {canEdit && (
                  <button
                    type="button"
                    className="secondary"
                    aria-expanded={editing === item.id}
                    onClick={() => { setEditing((open) => (open === item.id ? null : item.id)); setPriceSince(farmToday()); }}
                  >
                    <Icons.editar /> Alterar preço
                  </button>
                )}
                <button
                  type="button"
                  className="link-btn quiet"
                  aria-expanded={Boolean(history[item.id])}
                  onClick={() => void toggleHistory(item.id)}
                >
                  Histórico de preço
                </button>
              </div>

              {canEdit && editing === item.id && (
                <form
                  className="supply-price"
                  onSubmit={(event) => {
                    event.preventDefault();
                    void guard(async () => {
                      if (priceSince === farmToday()) await onUpdatePrice(token, item.id, Number(prices[item.id]));
                      else await onUpdatePrice(token, item.id, Number(prices[item.id]), priceSince);
                      setEditing(null);
                    });
                  }}
                >
                  <label htmlFor={`price-${item.id}`}>
                    Novo preço por kg — {item.name}
                  </label>
                  <input
                    id={`price-${item.id}`}
                    type="number"
                    step="0.00001"
                    min="0"
                    inputMode="decimal"
                    value={prices[item.id] ?? ""}
                    onChange={(event) =>
                      setPrices((current) => ({
                        ...current,
                        [item.id]: event.target.value,
                      }))
                    }
                  />
                  <p className="hint">
                    O preço anterior fica no histórico, com a data em que valia.
                  </p>
                  <label htmlFor={`price-since-${item.id}`}>Preço do insumo válido a partir de</label>
                  <input id={`price-since-${item.id}`} type="date" max={farmToday()} required value={priceSince} onChange={e => setPriceSince(e.target.value)} />
                  <button type="submit" disabled={busy || !prices[item.id]}>
                    Salvar preço
                  </button><button type="button" className="secondary" onClick={() => setEditing(null)}>Cancelar</button>
                </form>
              )}
            </li>
          ))}
        </ul>
      )}

    </section>
  );
}
