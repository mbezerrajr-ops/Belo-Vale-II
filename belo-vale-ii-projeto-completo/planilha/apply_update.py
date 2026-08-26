# -*- coding: utf-8 -*-
import json, re, openpyxl
from copy import copy

BASE = "/tmp/claude-0/-home-user-Balancetes-porto/6cc42e22-5678-5e79-9cba-4f9e401567a5/scratchpad/leo_figueiroa"

with open(f"{BASE}/transcricao.json", encoding="utf-8") as f:
    rows = json.load(f)

wb = openpyxl.load_workbook(f"{BASE}/pesagem_leite.xlsx", data_only=False)
ws = wb["LOTES"]

COL_NOME, COL_SIT, COL_LOTE, COL_PARTO, COL_AU, COL_DEL, COL_FASE, COL_RES = 2,3,4,5,47,48,49,50

# build id -> [(row, nome, sit, lote)] index from current sheet (rows 3..255)
id_index = {}
last_data_row = 255
for r in range(3, last_data_row+1):
    nome = ws.cell(row=r, column=COL_NOME).value
    if not nome:
        continue
    m = re.search(r'-\s*(\d+)', nome)
    cid = m.group(1) if m else None
    id_index.setdefault(cid, []).append((r, nome, ws.cell(row=r, column=COL_SIT).value, ws.cell(row=r, column=COL_LOTE).value))

# explicit holds (nao aplicar - IDs ilegiveis/ambiguos ou conflitos) - chave = (pagina, num)
HOLDS = {
    ("L1P1", 2): "ID ilegivel na foto ('SCHUMA'); nao localizada no cadastro",
    ("L1P2", 11): "ID/nome incertos ('BABACU'); nao localizada no cadastro",
    ("L2P2", 10): "ID ilegivel na foto ('PANDORA'); nao foi possivel confirmar o numero",
    ("L3P1", 12): "ID ilegivel na foto ('PONTA CURTA')",
    ("L3P1", 15): "ID ilegivel na foto ('GIGANTE'); numero pode colidir com outra vaca",
}
# nao alterar o LOTE (so atualizar producao) para estes casos especificos, com nota de conflito
KEEP_LOTE_ONLY_TOTAL = {
    ("L1P2", 8): "ID 647 (NEGUINHA) ja pertence ha meses ao LOTE 2 no cadastro; apareceu na folha do Lote 1 sem seta de correcao, mas ha outra vaca de nome muito parecido (NEGUINHA-767) legitimamente no Lote 1 na mesma folha -> suspeita de troca de ficha/numero. Mantive o LOTE 2 do cadastro e so atualizei a producao; confirmar com quem preencheu a ficha.",
}
# desambiguacao por nome quando o ID tem mais de uma vaca cadastrada
NAME_DISAMBIG = {
    ("L1P1", 7): "BORBOLETA",   # -> 'BORBOLETA 3 - 016 VERDE'
    ("L2P2", 12): "BELMONTE",   # -> 'BELMONTE - 016'
}

applied = []       # log de alteracoes em vacas existentes
new_cows = []       # log de vacas novas inseridas
holds = []          # log de linhas nao aplicadas

next_new_row = last_data_row + 1  # 256

def title_name(n):
    return n.strip().title()

for (pagina, num, pid, nome, manha, tarde, total, lote_pagina, lote_corr, conf, obs) in rows:
    key = (pagina, num)
    if key in HOLDS:
        holds.append({"pagina": pagina, "num": num, "id": pid, "nome": nome, "manha": manha,
                       "tarde": tarde, "total": total, "motivo": HOLDS[key]})
        continue

    lote_final = lote_corr or lote_pagina
    candidates = id_index.get(pid, [])

    match = None
    if len(candidates) == 1:
        match = candidates[0]
    elif len(candidates) > 1:
        if key in NAME_DISAMBIG:
            target = NAME_DISAMBIG[key]
            for cand in candidates:
                if target in cand[1].upper():
                    match = cand
                    break
        if match is None:
            # nao foi possivel desambiguar com seguranca
            holds.append({"pagina": pagina, "num": num, "id": pid, "nome": nome, "manha": manha,
                           "tarde": tarde, "total": total,
                           "motivo": f"ID {pid} corresponde a mais de uma vaca no cadastro ({[c[1] for c in candidates]}) e nao foi possivel desambiguar com seguranca"})
            continue

    if match:
        r, nome_cad, sit_cad, lote_cad = match
        keep_lote_only = key in KEEP_LOTE_ONLY_TOTAL
        old_total = ws.cell(row=r, column=COL_AU).value
        old_lote = ws.cell(row=r, column=COL_LOTE).value
        ws.cell(row=r, column=COL_AU).value = total
        if not keep_lote_only:
            ws.cell(row=r, column=COL_LOTE).value = lote_final
        # ativa Sit=VL se a vaca estava seca mas produziu hoje
        if sit_cad not in (None, "VL") and total and total > 0:
            ws.cell(row=r, column=COL_SIT).value = "VL"
        applied.append({
            "linha": r, "id": pid, "nome_cadastro": nome_cad, "nome_foto": nome,
            "lote_antigo": old_lote, "lote_novo": (old_lote if keep_lote_only else lote_final),
            "total_antigo": old_total, "total_novo": total,
            "obs": (KEEP_LOTE_ONLY_TOTAL.get(key) or obs)
        })
    else:
        # vaca nova -> insere na proxima linha livre, copiando formulas de DEL/Fase/Resultado
        r = next_new_row
        next_new_row += 1
        sit_new = "VS" if "SECA" in (obs or "").upper() else "VL"
        lote_new = None if sit_new == "VS" else lote_final
        ws.cell(row=r, column=COL_NOME).value = f"{title_name(nome)} - {pid}"
        ws.cell(row=r, column=COL_SIT).value = sit_new
        ws.cell(row=r, column=COL_LOTE).value = lote_new
        ws.cell(row=r, column=COL_AU).value = total
        for col in (COL_DEL, COL_FASE, COL_RES):
            src = ws.cell(row=last_data_row, column=col)
            dst = ws.cell(row=r, column=col)
            dst.value = re.sub(r'(?<=[A-Z\$])' + str(last_data_row) + r'(?!\d)', str(r), src.value) if isinstance(src.value, str) else src.value
            if src.has_style:
                dst._style = copy(src._style)
        new_cows.append({"linha": r, "id": pid, "nome": f"{title_name(nome)} - {pid}",
                          "lote": lote_new, "sit": sit_new, "total": total, "obs": obs})

# extend dependent formula ranges so new rows are counted
tab = wb["Tabela"]
for cell in ("F6", "F7", "F8"):
    tab[cell].value = tab[cell].value.replace("$D$260", "$D$400")
custo = wb["CUSTO DA RAÇÃO"]
for cell in ("D9", "D22", "D38"):
    custo[cell].value = custo[cell].value.replace("$D$292", "$D$400").replace("$AU$292", "$AU$400")

wb.save(f"{BASE}/pesagem_leite_ATUALIZADA.xlsx")

print("APPLIED (existing cows updated):", len(applied))
print("NEW COWS inserted:", len(new_cows))
print("HOLDS (not applied):", len(holds))

with open(f"{BASE}/update_log.json", "w", encoding="utf-8") as f:
    json.dump({"applied": applied, "new_cows": new_cows, "holds": holds}, f, ensure_ascii=False, indent=1)
