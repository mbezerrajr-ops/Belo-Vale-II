/**
 * O "hoje" das telas é o dia da fazenda — UTC−3 fixo, o mesmo de
 * `app/core/farm_clock.py` no servidor.
 *
 * Usar o fuso do aparelho quebra de verdade: o servidor recusa coleta e baixa
 * com data no futuro comparando com o dia da fazenda. Um celular em outro
 * fuso (ou o CI, que roda em UTC) calculava "amanhã" das 21h à meia-noite de
 * Brasília e o lançamento era recusado — foi assim que o E2E falhou no CI
 * rodando 00:30 UTC.
 */

import { describe, expect, it } from "vitest";

import { farmToday } from "./dates";

describe("farmToday", () => {
  it("vira o dia às 00:00 da fazenda, não às 00:00 UTC", () => {
    // 00:30 UTC = 21:30 do dia anterior na fazenda.
    expect(farmToday(new Date("2026-09-20T00:30:00Z"))).toBe("2026-09-19");
    // 03:30 UTC = 00:30 da fazenda: já virou.
    expect(farmToday(new Date("2026-09-20T03:30:00Z"))).toBe("2026-09-20");
  });

  it("não depende do fuso do aparelho", () => {
    // O mesmo instante, escrito em três fusos, dá o mesmo dia de fazenda.
    const instante = "2026-09-20T12:00:00Z";
    expect(farmToday(new Date(instante))).toBe("2026-09-20");
    expect(farmToday(new Date("2026-09-20T09:00:00-03:00"))).toBe("2026-09-20");
    expect(farmToday(new Date("2026-09-20T14:00:00+02:00"))).toBe("2026-09-20");
  });

  it("atravessa a virada do mês", () => {
    expect(farmToday(new Date("2026-10-01T02:00:00Z"))).toBe("2026-09-30");
  });
});
