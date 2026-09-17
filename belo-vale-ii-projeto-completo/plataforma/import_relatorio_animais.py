# -*- coding: utf-8 -*-
"""Importa o "RELATÓRIO DE TODOS ANIMAIS" (PDF) para a base de vacas da plataforma.

Atualiza Lote, Data do último parto e DEL das vacas já cadastradas, cadastra as
que ainda não existem e preserva o histórico de medições de leite.

Uso:
    pip install pdfplumber
    python import_relatorio_animais.py "../../docs/RELÁTORIO DE TODOS ANIMAIS.pdf"        # simulação
    python import_relatorio_animais.py "../../docs/RELÁTORIO DE TODOS ANIMAIS.pdf" --write

O relatório é lido pelas colunas do PDF (x do texto): brinco, nome, lote,
data do último parto e DEL. O DEL do relatório equivale a (hoje - último parto).
"""
import collections
import json
import os
import re
import sys
import unicodedata
from datetime import date

import pdfplumber

PDF = sys.argv[1] if len(sys.argv) > 1 else '../../docs/RELÁTORIO DE TODOS ANIMAIS.pdf'
PLAT = os.path.dirname(os.path.abspath(__file__)) + '/'
SAIDA = PLAT + 'import_relatorio_animais_ultimo_relatorio.txt'
HOJE = date.today()
TAG_INI = '<script id="state-data" type="application/json">'
TAG_FIM = '</script>'

# Limites (em pt) entre as colunas do PDF.
COLS = [(0, 120, 'brinco'), (120, 300, 'nome'), (300, 450, 'lote'), (450, 545, 'data'), (545, 900, 'delx')]


def ler_pdf(caminho):
    linhas = []
    with pdfplumber.open(caminho) as pdf:
        for pagina in pdf.pages:
            por_linha = collections.defaultdict(list)
            for w in pagina.extract_words():
                por_linha[round(w['top'])].append(w)
            for top in sorted(por_linha):
                ws = sorted(por_linha[top], key=lambda w: w['x0'])
                reg = {nome: ' '.join(w['text'] for w in ws if a <= w['x0'] < b).strip() for a, b, nome in COLS}
                if not reg['brinco'] or reg['brinco'] == 'Brinco' or reg['brinco'].startswith(('Fazenda', 'FORMUL', 'Total')):
                    continue
                linhas.append(reg)
    return linhas

LOTE_MAP = {
    'Lote 1': 'LOTE 1', 'Lote 2': 'LOTE 2', 'Lote 3': 'LOTE 3',
    'Pré-Parto': 'PRÉ-PARTO', 'PIQUETES / REPASSE': 'PIQUETES / REPASSE',
    'ENGORDA': 'ENGORDA', 'ENGENHO': 'ENGENHO', 'INSERLEITE': 'INSERLEITE',
    'BEZERREIRO': 'BEZERREIRO', 'CAJARANAS': 'CAJARANAS', 'PALMA': 'PALMA',
    'COLEGIO': 'COLÉGIO', 'ABREU': 'ABREU',
}

def norm(s):
    s = ''.join(c for c in unicodedata.normalize('NFD', (s or '').upper()) if unicodedata.category(c) != 'Mn')
    return re.sub(r'\s+', ' ', s).strip()

def keynum(s):
    m = re.match(r'^(?:B\d+-)?0*(\d+)\b', str(s or '').strip())
    return int(m.group(1)) if m else None

def iso(d):
    if not re.match(r'^\d{2}/\d{2}/\d{4}$', d):
        return ''
    dd, mm, yy = d.split('/')
    return f'{yy}-{mm}-{dd}'

rows = ler_pdf(PDF)
html = open(PLAT + 'platform_ATUAL_publicado.html', encoding='utf-8').read()
m = re.search(r'(<script id="state-data" type="application/json">)([\s\S]*?)(</script>)', html)
state = json.loads(m.group(2))
base = state['vacas']

log = open(SAIDA, 'w', encoding='utf-8')
P = lambda *a: print(*a, file=log)

# ---------- matching ----------
by_num = collections.defaultdict(list)
by_nome = collections.defaultdict(list)
for v in base:
    k = keynum(v.get('numero'))
    if k is not None:
        by_num[k].append(v)
    by_nome[norm(v.get('nome'))].append(v)

usados = set()          # id(v) das vacas da base já casadas
par = {}                # índice da linha do pdf -> vaca da base
ambig, divergentes = [], []

# passo 0: brincos de outra série (B1-/B2-) casam primeiro pelo nome,
# porque a numeração dessa série não corresponde à numeração da base.
for i, r in enumerate(rows):
    if not r['brinco'].upper().startswith('B'):
        continue
    cands = [v for v in by_nome.get(norm(r['nome']), []) if id(v) not in usados]
    if len(cands) == 1:
        par[i] = cands[0]
        usados.add(id(cands[0]))

# passo 1: brinco (número), com nome como desempate
for i, r in enumerate(rows):
    if i in par:
        continue
    k = keynum(r['brinco'])
    cands = [v for v in by_num.get(k, []) if id(v) not in usados] if k is not None else []
    if not cands:
        continue
    if len(cands) > 1:
        exatos = [v for v in cands if norm(v['nome']) == norm(r['nome'])]
        if len(exatos) == 1:
            cands = exatos
        else:
            ambig.append((r['brinco'], r['nome'], [v['numero'] + '/' + v['nome'] for v in cands]))
            continue
    v = cands[0]
    par[i] = v
    usados.add(id(v))
    if norm(v['nome']) != norm(r['nome']):
        divergentes.append((r['brinco'], r['nome'], v['numero'], v['nome']))

# passo 2: nome exato (único dos dois lados)
for i, r in enumerate(rows):
    if i in par:
        continue
    cands = [v for v in by_nome.get(norm(r['nome']), []) if id(v) not in usados]
    if len(cands) == 1:
        par[i] = cands[0]
        usados.add(id(cands[0]))

# ---------- aplicação ----------
alt_lote = alt_parto = novos = 0
mudancas = []
for i, r in enumerate(rows):
    lote = LOTE_MAP[r['lote']]
    parto = iso(r['data'])
    del_ = int(r['delx']) if r['delx'] else ''
    nome = r['nome'] if norm(r['nome']) != norm(r['brinco']) else r['brinco']
    if i in par:
        v = par[i]
        if v.get('lote') != lote:
            mudancas.append(('lote', v['numero'], v['nome'], v.get('lote', ''), lote)); alt_lote += 1
        v['lote'] = lote
        if parto and v.get('parto') != parto:
            mudancas.append(('parto', v['numero'], v['nome'], v.get('parto', ''), parto)); alt_parto += 1
        if parto:
            v['parto'] = parto
        v['del'] = del_
        v['brinco'] = r['brinco']
    else:
        novos += 1
        nid = 'v' + re.sub(r'[^A-Za-z0-9]', '', r['brinco'])
        existentes = {x['id'] for x in base}
        if nid in existentes:
            nid += '_' + str(i)
        base.append({
            'id': nid, 'numero': r['brinco'], 'brinco': r['brinco'], 'nome': nome,
            'lote': lote, 'nascimento': '', 'parto': parto, 'peso': '',
            'media': 0, 'del': del_,
            'situacao': 'Em lactação' if del_ != '' else 'Seca',
            'ultimaMedicao': '', 'status': 'Ativo', 'historico': [],
        })

# DEL para quem já estava na base e não veio no relatório: campo criado vazio
for v in base:
    v.setdefault('del', '')

# ---------- relatório ----------
P('Registros no PDF: %d | vacas na base antes: %d | depois: %d' % (len(rows), len(base) - novos, len(base)))
P('Casadas com a base: %d | novas cadastradas: %d' % (len(par), novos))
P('Lote alterado: %d | Data último parto alterada: %d' % (alt_lote, alt_parto))
P('')
P('--- Vacas da base que NÃO aparecem no relatório (mantidas, sem alteração): %d' %
  sum(1 for v in base if 'brinco' not in v))
for v in base:
    if 'brinco' not in v:
        P('    %-12s %-24s lote=%-18s situacao=%-12s leituras=%d' %
          (v['numero'], v['nome'], v.get('lote', ''), v.get('situacao', ''), len(v.get('historico', []))))
P('')
P('--- Nome diverge entre relatório e base (nome da base foi mantido): %d' % len(divergentes))
for d in divergentes:
    P('    brinco %-8s pdf=%-20s base=%s/%s' % d)
P('')
P('--- Ambíguas (não atualizadas): %d' % len(ambig))
for a in ambig:
    P('    ', a)
P('')
P('--- Alterações aplicadas: %d' % len(mudancas))
for c in mudancas:
    P('    %-6s %-12s %-24s %-14s -> %s' % c)

# checagem: histórico preservado
P('')
P('Vacas com histórico de leite: %d | leituras totais: %d' %
  (sum(1 for v in base if v.get('historico')), sum(len(v.get('historico', [])) for v in base)))
log.close()

if '--write' in sys.argv:
    novo_json = json.dumps(state, ensure_ascii=False)
    tmpl = open(PLAT + 'platform_ATUAL_template.html', encoding='utf-8').read()
    ini = tmpl.index(TAG_INI) + len(TAG_INI)
    fim = tmpl.index(TAG_FIM, ini)
    pub = tmpl[:ini] + novo_json + tmpl[fim:]
    open(PLAT + 'platform_ATUAL_publicado.html', 'w', encoding='utf-8').write(pub)
    plano = {k: state[k] for k in state}
    plano['vacas'] = [{k: vv for k, vv in v.items() if k != 'historico'} for v in state['vacas']]
    json.dump(plano, open(PLAT + 'state_dados_atuais.json', 'w', encoding='utf-8'), ensure_ascii=False)
    print('gravado')
