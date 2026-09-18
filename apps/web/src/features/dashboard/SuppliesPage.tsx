import { useEffect, useState } from "react";

import {
  createSupply,
  listSupplies,
  setMilkPrice,
  updateSupplyPrice,
} from "../../api/client";
import type { Supply } from "../../api/types";

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
  onList?: (token: string) => Promise<Supply[]>;
  onUpdatePrice?: (
    token: string,
    supplyId: string,
    pricePerKg: number,
  ) => Promise<Supply>;
  onCreate?: (token: string, name: string, pricePerKg: number) => Promise<Supply>;
  onSetMilkPrice?: (token: string, pricePerLiter: number) => Promise<void>;
}

const currency = new Intl.NumberFormat("pt-BR", {
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
}: Props): JSX.Element {
  const [supplies, setSupplies] = useState<Supply[] | null>(null);
  const [prices, setPrices] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [newName, setNewName] = useState("");
  const [newPrice, setNewPrice] = useState("");
  const [milk, setMilk] = useState(milkPrice === null ? "" : String(milkPrice));

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
      <h2>Insumos e dieta</h2>
      <p className="hint">
        O preço de cada insumo, multiplicado pela dieta do lote, é o custo
        diário que aparece no painel.
      </p>

      {error && <p role="alert">{error}</p>}

      {canEdit && (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void guard(() => onSetMilkPrice(token, Number(milk)));
          }}
        >
          <h3>Preço do leite</h3>
          <label htmlFor="milk-price">Preço por litro (R$)</label>
          <input
            id="milk-price"
            type="number"
            step="0.01"
            min="0"
            value={milk}
            onChange={(event) => setMilk(event.target.value)}
          />
          <p className="hint">Base do cálculo de receita e lucro.</p>
          <button type="submit" disabled={busy || milk === ""}>
            Salvar preço do leite
          </button>
        </form>
      )}

      {supplies === null ? (
        <p>Carregando…</p>
      ) : (
        <ul className="supply-list">
          {supplies.map((item) => (
            <li key={item.id}>
              <h3>{item.name}</h3>
              <p className="price">{currency.format(item.price_per_kg)} / kg</p>

              <table className="diet">
                <thead>
                  <tr>
                    <th>Lote</th>
                    <th>kg/dia</th>
                    <th>Custo/dia</th>
                  </tr>
                </thead>
                <tbody>
                  {item.diets.map((diet) => (
                    <tr key={diet.lote}>
                      <td>{diet.lote}</td>
                      <td>{diet.kg_per_day}</td>
                      <td>{currency.format(diet.kg_per_day * item.price_per_kg)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>

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
                  <button
                    type="submit"
                    disabled={busy || !prices[item.id]}
                  >
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
