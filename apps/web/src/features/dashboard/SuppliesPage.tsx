import { useEffect, useState, type CSSProperties } from "react";

import {
  createSupply,
  getSupplyPrices,
  listSupplies,
  setMilkPrice,
  updateSupplyPrice,
} from "../../api/client";
import type { Supply, SupplyPrice } from "../../api/types";
import { brDate } from "../../ui/dates";
import { BarList, fmt } from "../../ui/charts";
import { PageHeader } from "../../ui/PageHeader";

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
  onMilkPriceSaved?: (pricePerLiter: number) => void;
  onList?: (token: string) => Promise<Supply[]>;
  onUpdatePrice?: (
    token: string,
    supplyId: string,
    pricePerKg: number,
  ) => Promise<Supply>;
  onCreate?: (token: string, name: string, pricePerKg: number) => Promise<Supply>;
  onSetMilkPrice?: (token: string, pricePerLiter: number) => Promise<void>;
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
  return body?.detail ?? "Não foi possível completar a ação. Tente novamente.";
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
      <PageHeader title="Insumos e dieta">
        Preço do insumo × dieta do lote = o custo diário que aparece no painel.
      </PageHeader>

      {error && <p role="alert">{error}</p>}

      {canEdit && (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            const price = Number(milk);
            setMilkSaved(null);
            void guard(async () => {
              await onSetMilkPrice(token, price);
              setMilkSaved(price);
              onMilkPriceSaved?.(price);
            });
          }}
        >
          <h3>Preço do leite</h3>
          <label htmlFor="milk-price">Preço por litro (R$)</label>
          <input
            id="milk-price"
            type="number"
            step="0.01"
            min="0"
            inputMode="decimal"
            value={milk}
            onChange={(event) => setMilk(event.target.value)}
          />
          <p className="hint">Base do cálculo de receita e lucro.</p>
          <button type="submit" disabled={busy || milk === ""}>
            Salvar preço do leite
          </button>
          {milkSaved !== null && (
            <p role="status">
              Preço do leite salvo: R$ {milkSaved.toLocaleString("pt-BR", { minimumFractionDigits: 2 })}{" "}
              por litro.
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
              <div className="row-between">
                <h3>{item.name}</h3>
                <p className="price">{precise.format(item.price_per_kg)} / kg</p>
              </div>
              <button
                type="button"
                className="link-btn"
                aria-expanded={Boolean(history[item.id])}
                onClick={() => void toggleHistory(item.id)}
              >
                Histórico de preço
              </button>
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

              <div className="table-wrap">
                <table className="diet">
                  <thead>
                    <tr>
                      <th>Lote</th>
                      <th className="num">kg/dia</th>
                      <th className="num">Custo/dia</th>
                    </tr>
                  </thead>
                  <tbody>
                    {item.diets.map((diet) => (
                      <tr key={diet.lote}>
                        <td>{diet.lote}</td>
                        <td className="num">{diet.kg_per_day}</td>
                        <td className="num">{fmt.brl(diet.kg_per_day * item.price_per_kg)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {canEdit && (
                <form
                  onSubmit={(event) => {
                    event.preventDefault();
                    void guard(() =>
                      onUpdatePrice(token, item.id, Number(prices[item.id])),
                    );
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
                  <button type="submit" disabled={busy || !prices[item.id]}>
                    Salvar preço
                  </button>
                </form>
              )}
            </li>
          ))}
        </ul>
      )}

      {canEdit && (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void guard(() => onCreate(token, newName.trim(), Number(newPrice)));
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
          </button>
        </form>
      )}
    </section>
  );
}
