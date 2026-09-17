"""Build the printable manual-reconciliation report from canonical project data."""

from __future__ import annotations

import html
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PLATFORM = ROOT / "belo-vale-ii-projeto-completo" / "plataforma"
sys.path.insert(0, str(PLATFORM))

from import_relatorio_animais import apply_report_rows, read_pdf_rows  # noqa: E402
from state_contract import find_del_situation_warnings  # noqa: E402


OUTPUT = Path(__file__).with_name("conflitos-reconciliacao-manual.html")
CANONICAL = PLATFORM / "state_canonical.json"
REPORT_PDF = next((ROOT / "docs").glob("REL*ANIMAIS.pdf"))
REPORT_DATE = "17/09/2026"

CANDIDATE_PAIRS = (
    ("125", "MARINGÁ", "B2-687", "Maringa"),
    ("205", "REVISTA", "827", "Revista"),
    ("604", "CARINHOSA", "832", "Carinhosa"),
    ("157", "CIGANA", "821", "Cigana"),
    ("474", "SURUBIM", "846", "Surubim"),
    ("440", "ARIZONA", "1001", "Arizona"),
    ("19", "BOLINHA", "956", "Bolinha"),
    ("626", "BOLINHA", "956", "Bolinha"),
    ("143", "BURGUESA", "B2-662", "BURGUESA"),
    ("155", "CARINA", "B2-658", "CARINA"),
    ("147", "CARRAPETA", "B2-664", "CARRAPETA"),
    ("46", "ESMERALDA", "812", "Esmeralda"),
    ("78", "ESPERANÇA", "B1-263", "ESPERANÇA"),
    ("009 VERMELHO", "FAÍSCA", "434", "FAÍSCA"),
    ("220", "JARDINEIRA", "1015", "Jardineira"),
    ("702", "MAÇA", "B2-663", "MAÇA"),
    ("686", "MEDALHA", "879", "Medalha"),
    ("635", "NEBLINA", "767", "NEBLINA"),
    ("96", "PALOMA", "B2-584", "PALOMA"),
    ("10", "TIETA", "964", "Tieta"),
    ("498", "Meias Branca", "448", "MEIAS BRANCA"),
    ("682", "Rainha", "B2-680", "RAINHA"),
    ("141", "Fumaca", "441", "FUMAÇA"),
    ("519", "Branquinha", "B2-549", "BRANQUINHA"),
    ("133", "Bruna", "433", "BRUNA"),
    ("862", "Saia Branca", "861", "SAIA BRANCA"),
    ("508", "Princesa", "B2-548", "PRINCESA"),
)

PROJECT_DECISIONS = (
    (
        "Todo arquivo submetido deverá conter todo o rebanho?",
        "Não. O sistema deve aceitar arquivos parciais e incrementais, desde que o "
        "escopo seja declarado.",
        "O arquivo pode representar apenas um lote, uma ordenha ou um grupo novo. "
        "Exigir o rebanho completo transformaria uma ausência no arquivo em uma falsa "
        "remoção e colocaria o histórico em risco.",
    ),
    (
        "Conflito significa substituição?",
        "Não. Conflito é um sinal de dados incompatíveis que bloqueia a atualização "
        "automática daquele campo.",
        "Substituir antes de confirmar identidade e precedência pode apagar o dado "
        "correto. A substituição só ocorre após decisão explícita e auditável.",
    ),
    (
        "O que acontece quando um animal não aparece no arquivo?",
        "O cadastro, a última medição e todo o histórico permanecem inalterados até "
        "chegar uma atualização identificada para esse animal.",
        "Não aparecer em um arquivo parcial não comprova venda, descarte, óbito, "
        "inatividade nem produção zero.",
    ),
    (
        "Qual identificador determina a correspondência?",
        "O brinco deve ser a chave operacional primária, combinado com a origem ou "
        "fazenda quando houver possibilidade de repetição entre rebanhos.",
        "Nomes variam, podem se repetir e sofrem erros de digitação. Um identificador "
        "estável reduz fusões e atualizações no animal errado.",
    ),
    (
        "Nome igual significa que é o mesmo animal?",
        "Não. Registros com brincos diferentes permanecem separados até existirem "
        "evidências independentes de que representam o mesmo animal.",
        "A base já contém nomes repetidos. Usar apenas o nome pode fundir históricos "
        "de animais distintos.",
    ),
    (
        "Como tratar o mesmo brinco com nomes diferentes?",
        "Preservar o nome cadastrado, registrar a divergência e solicitar conferência "
        "manual antes de renomear.",
        "O brinco sugere a mesma identidade, mas uma diferença relevante de nome pode "
        "indicar erro de leitura, troca de brinco ou cadastro incorreto.",
    ),
    (
        "Como cadastrar um animal realmente novo?",
        "Criar um novo cadastro somente quando houver brinco confiável, contexto de "
        "origem e ausência de colisão com identificadores existentes.",
        "Esse conjunto mínimo evita criar duplicidades por diferença de grafia ou por "
        "um brinco lido incorretamente.",
    ),
    (
        "Uma nova medição substitui a medição anterior?",
        "Não. A nova medição deve ser acrescentada ao histórico com sua data de "
        "referência; a última medição passa a apontar para o evento mais recente.",
        "Medições são eventos temporais. Sobrescrever elimina a série histórica e "
        "impede auditoria, comparação e correção posterior.",
    ),
    (
        "Quando lote, situação e último parto podem ser atualizados?",
        "Somente quando o arquivo trouxer o campo explicitamente, a fonte for "
        "autorizada e o animal estiver identificado sem ambiguidade.",
        "Campo ausente não significa campo vazio. Atualizações implícitas podem apagar "
        "informações válidas de um arquivo anterior.",
    ),
    (
        "Como registrar a mudança de lote de um animal?",
        "A vaca pode mudar de lote ao longo do tempo: lote não é parte da identidade "
        "nem bloqueia a medição. Manter um histórico de lotação (lote, vigência, "
        "origem e revisor) em vez de sobrescrever o lote atual.",
        "Um lote novo não deve apagar silenciosamente o lote anterior, e um relatório "
        "histórico não pode ser reinterpretado usando somente o lote de hoje. A "
        "medição também preserva o lote observado no momento em que foi registrada.",
    ),
    (
        "Como tratar DEL vazio?",
        "Não inventar nem zerar o DEL. Confirmar a data do último parto ou corrigir a "
        "situação do animal com evidência.",
        "DEL depende do evento reprodutivo e da data de referência. Um valor fabricado "
        "contamina indicadores produtivos e reprodutivos.",
    ),
    (
        "O arquivo deve declarar se é parcial ou completo?",
        "Sim. Exigir metadados de escopo, fazenda ou origem, data de referência, tipo "
        "de relatório e indicação de parcial ou completo.",
        "Sem esses metadados o sistema não consegue distinguir uma atualização "
        "incremental de um retrato completo do rebanho.",
    ),
    (
        "Quando um arquivo pode substituir uma baseline?",
        "Somente quando for declarado como retrato completo, passar por validação de "
        "totais e identificadores, possuir versão e tiver aprovação humana.",
        "Uma substituição ampla é difícil de reverter e pode remover dados que não "
        "estavam no escopo do arquivo.",
    ),
    (
        "Como desfazer uma importação incorreta?",
        "Registrar cada importação como um lote auditável e manter snapshot anterior "
        "ou operações inversas testadas.",
        "Origem, hash do arquivo, horário, operador e alterações por campo permitem "
        "identificar o impacto e restaurar o estado sem apagar eventos legítimos.",
    ),
)


def e(value: object) -> str:
    return html.escape(str(value or "—"))


def build_html() -> str:
    state = json.loads(CANONICAL.read_text(encoding="utf-8"))
    result = apply_report_rows(state, read_pdf_rows(REPORT_PDF))
    warnings = find_del_situation_warnings(result.state)
    divergences = result.match.divergences
    legacy_only = result.legacy_only

    expected = {
        "animais ausentes": (len(legacy_only), 141),
        "divergências de nome": (len(divergences), 13),
        "alertas de DEL": (len(warnings), 30),
        "pares candidatos": (len(CANDIDATE_PAIRS), 27),
    }
    invalid = [
        f"{label}: encontrado={actual}, esperado={wanted}"
        for label, (actual, wanted) in expected.items()
        if actual != wanted
    ]
    if invalid:
        raise RuntimeError("Baseline alterada; revise o relatório: " + "; ".join(invalid))

    divergence_rows = "\n".join(
        f"""
        <tr>
          <td class="check">☐</td>
          <td>{e(tag)}</td>
          <td>{e(pdf_name)}</td>
          <td>{e(number)} / {e(base_name)}</td>
          <td class="write-cell">Nome confirmado: ____________________<br>Evidência: ________________________</td>
        </tr>"""
        for tag, pdf_name, number, base_name in divergences
    )
    warning_rows = "\n".join(
        f"""
        <tr>
          <td class="check">☐</td>
          <td>{e(item.tag)}</td>
          <td>{e(item.number)}</td>
          <td>{e(item.name)}</td>
          <td>{e(item.situation)}</td>
          <td class="write-cell">Último parto: ____/____/______<br>Fonte: ____________________________</td>
        </tr>"""
        for item in warnings
    )
    candidate_rows = "\n".join(
        f"""
        <tr class="{'risk-row' if legacy_name.upper() == 'BOLINHA' else ''}">
          <td>{e(legacy_number)} / {e(legacy_name)}</td>
          <td>{e(report_tag)} / {e(report_name)}</td>
          <td>Não relacionar automaticamente. Investigar somente se houver evidência
          adicional de identidade.</td>
        </tr>"""
        for legacy_number, legacy_name, report_tag, report_name in CANDIDATE_PAIRS
    )
    legacy_rows = "\n".join(
        f"""
        <tr>
          <td>{e(number)}</td>
          <td>{e(name)}</td>
          <td>{e(lot)}</td>
          <td>{e(situation)}</td>
          <td>{history_count}</td>
          <td>Preservado — aguardar atualização explícita deste animal.</td>
        </tr>"""
        for number, name, lot, situation, history_count in legacy_only
    )
    project_decision_rows = "\n".join(
        f"""
        <tr>
          <td>{e(question)}</td>
          <td>{e(recommendation)}</td>
          <td>{e(rationale)}</td>
          <td class="write-cell"></td>
          <td class="write-cell"></td>
        </tr>"""
        for question, recommendation, rationale in PROJECT_DECISIONS
    )

    return f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Regras e verificações de reconciliação — Belo Vale II</title>
  <style>
    :root {{
      --ink: #18342b;
      --muted: #5e6f68;
      --green: #285e4a;
      --green-soft: #e9f2ed;
      --cream: #f8f5ed;
      --amber: #a76413;
      --amber-soft: #fff1d8;
      --red: #9c382e;
      --red-soft: #fbe8e5;
      --line: #cbd7d1;
      --white: #ffffff;
    }}
    * {{ box-sizing: border-box; }}
    @page {{
      size: A4;
      margin: 14mm 12mm 16mm;
    }}
    body {{
      margin: 0;
      color: var(--ink);
      background: var(--white);
      font-family: "Segoe UI", Arial, sans-serif;
      font-size: 9.4pt;
      line-height: 1.42;
    }}
    h1, h2, h3 {{ break-after: avoid; color: var(--ink); }}
    h1 {{ margin: 0; font-size: 26pt; line-height: 1.08; }}
    h2 {{
      margin: 0 0 4mm;
      padding-bottom: 2mm;
      border-bottom: 2px solid var(--green);
      font-size: 17pt;
    }}
    h3 {{ margin: 5mm 0 2mm; font-size: 12pt; }}
    p {{ margin: 0 0 3mm; }}
    ul, ol {{ margin: 2mm 0 4mm; padding-left: 6mm; }}
    li {{ margin-bottom: 1.5mm; }}
    .cover {{
      min-height: 267mm;
      padding: 16mm;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      color: var(--white);
      background:
        linear-gradient(150deg, rgba(18, 57, 44, .97), rgba(43, 99, 76, .94)),
        radial-gradient(circle at top right, #82a78f, transparent 45%);
      break-after: page;
    }}
    .cover .eyebrow {{
      font-size: 10pt;
      font-weight: 700;
      letter-spacing: .16em;
      text-transform: uppercase;
      color: #cce2d6;
    }}
    .cover h1 {{ max-width: 150mm; color: var(--white); }}
    .cover .subtitle {{
      max-width: 145mm;
      margin-top: 8mm;
      font-size: 14pt;
      color: #e5f0e9;
    }}
    .cover-grid {{
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: 3mm;
      margin-top: 12mm;
    }}
    .cover-stat {{
      padding: 5mm;
      border: 1px solid rgba(255,255,255,.3);
      border-radius: 3mm;
      background: rgba(255,255,255,.08);
    }}
    .cover-stat strong {{ display: block; font-size: 22pt; }}
    .cover-meta {{
      padding-top: 5mm;
      border-top: 1px solid rgba(255,255,255,.35);
      font-size: 9pt;
      color: #d8e8df;
    }}
    .page {{ break-before: page; }}
    .section {{ padding: 2mm 0; }}
    .lead {{
      margin-bottom: 5mm;
      font-size: 11pt;
      color: #344e44;
    }}
    .callout {{
      margin: 4mm 0;
      padding: 4mm 5mm;
      border-left: 4px solid var(--green);
      border-radius: 1.5mm;
      background: var(--green-soft);
    }}
    .callout.warning {{ border-color: var(--amber); background: var(--amber-soft); }}
    .callout.danger {{ border-color: var(--red); background: var(--red-soft); }}
    .summary-grid {{
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: 3mm;
      margin: 5mm 0;
    }}
    .summary-card {{
      min-height: 32mm;
      padding: 4mm;
      border: 1px solid var(--line);
      border-radius: 2mm;
      background: var(--cream);
    }}
    .summary-card strong {{
      display: block;
      margin-bottom: 1mm;
      font-size: 20pt;
      color: var(--green);
    }}
    .flow {{
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 2mm;
      margin: 5mm 0;
    }}
    .flow div {{
      position: relative;
      padding: 4mm 3mm;
      border-radius: 2mm;
      color: var(--white);
      background: var(--green);
      text-align: center;
      font-weight: 700;
    }}
    .flow div:not(:last-child)::after {{
      content: "→";
      position: absolute;
      right: -4mm;
      top: 30%;
      z-index: 2;
      color: var(--green);
      font-size: 16pt;
    }}
    table {{
      width: 100%;
      margin: 3mm 0 5mm;
      border-collapse: collapse;
      table-layout: fixed;
      font-size: 8.2pt;
    }}
    thead {{ display: table-header-group; }}
    tr {{ break-inside: avoid; }}
    th {{
      padding: 2.2mm;
      border: 1px solid var(--green);
      color: var(--white);
      background: var(--green);
      text-align: left;
      font-size: 8pt;
    }}
    td {{
      min-height: 8mm;
      padding: 2mm;
      border: 1px solid var(--line);
      vertical-align: top;
    }}
    tbody tr:nth-child(even) {{ background: #f6f9f7; }}
    .check {{ width: 8mm; text-align: center; font-size: 13pt; }}
    .write-cell {{ height: 13mm; color: #50635b; }}
    .decision {{ min-width: 60mm; font-size: 7.6pt; }}
    .decision-table {{ font-size: 7.3pt; }}
    .decision-table td {{ padding: 1.7mm; }}
    .risk-row {{ background: var(--red-soft) !important; }}
    .tag {{
      display: inline-block;
      margin-right: 2mm;
      padding: 1mm 2mm;
      border-radius: 1mm;
      background: var(--green-soft);
      color: var(--green);
      font-weight: 700;
    }}
    .small {{ font-size: 8pt; color: var(--muted); }}
    .signoff {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8mm;
      margin-top: 14mm;
    }}
    .sign-line {{ padding-top: 12mm; border-bottom: 1px solid var(--ink); }}
    .footer-note {{
      margin-top: 6mm;
      padding-top: 3mm;
      border-top: 1px solid var(--line);
      font-size: 7.8pt;
      color: var(--muted);
    }}
  </style>
</head>
<body>
  <section class="cover">
    <div>
      <div class="eyebrow">Belo Vale II · Controle de qualidade de dados</div>
      <h1>Regras e verificações de reconciliação</h1>
      <p class="subtitle">
        Guia operacional para importar arquivos incrementais, preservar históricos e
        resolver somente os conflitos que exigem decisão humana.
      </p>
      <div class="cover-grid">
        <div class="cover-stat"><strong>30</strong>verificações manuais obrigatórias</div>
        <div class="cover-stat"><strong>13</strong>observações de nome, não bloqueiam</div>
        <div class="cover-stat"><strong>27</strong>coincidências não conclusivas</div>
        <div class="cover-stat"><strong>141</strong>cadastros preservados sem ação</div>
        <div class="cover-stat"><strong>0</strong>substituições automáticas</div>
      </div>
    </div>
    <div class="cover-meta">
      <strong>Versão 1.2 · {REPORT_DATE}</strong><br>
      Baseline: 401 animais · PDF: 260 registros · 260 correspondências por identificador<br>
      Estado analisado: <code>state_canonical.json</code>
    </div>
  </section>

  <section class="section">
    <h2>1. Objetivo e limite deste relatório</h2>
    <p class="lead">
      Este documento define como arquivos parciais devem atualizar a base sem apagar
      informações anteriores. Também organiza os poucos casos em que o sistema não possui
      evidência suficiente para tomar uma decisão sozinho.
    </p>
    <div class="summary-grid">
      <div class="summary-card"><strong>30</strong>verificações manuais obrigatórias</div>
      <div class="summary-card"><strong>13</strong>observações de nome, não bloqueiam</div>
      <div class="summary-card"><strong>27</strong>coincidências não conclusivas</div>
      <div class="summary-card"><strong>141</strong>cadastros preservados sem ação</div>
      <div class="summary-card"><strong>152</strong>leituras históricas preservadas</div>
    </div>
    <div class="callout danger">
      <strong>Regra de segurança:</strong> não apagar, fundir, renomear, trocar situação
      nem preencher DEL apenas por semelhança de nome. Toda decisão precisa registrar
      fonte, responsável e data.
    </div>

    <h3>Identidade do animal</h3>
    <p>
      O brinco é a única chave de identidade operacional deste rebanho. Nome é informação descritiva, não identificadora: a base contém nomes repetidos, e o
      mesmo nome em brincos diferentes significa animais diferentes. O nome não deve ser usado para localizar, casar ou fundir animais —
      nem como critério primário, nem como alternativa quando o brinco está ausente.
    </p>
    <div class="flow">
      <div>1. Buscar pelo brinco</div>
      <div>2. Registrar o método usado</div>
      <div>3. Sem brinco, não associar automaticamente</div>
      <div>4. Nome divergente é observação, não bloqueio</div>
    </div>

    <h3>Como interpretar o arquivo recente</h3>
    <p>
      O PDF recente pode conter outro grupo de gado e não representa necessariamente uma
      atualização completa dos animais antigos. Quando existe um brinco compatível, a nova
      informação é associada àquele cadastro. Quando um cadastro anterior não aparece,
      a medição e o histórico anteriores continuam válidos até que uma atualização explícita
      daquele animal seja fornecida.
    </p>
    <div class="flow">
      <div>1. Declarar o escopo</div>
      <div>2. Identificar o animal</div>
      <div>3. Acrescentar o evento</div>
      <div>4. Preservar o restante</div>
    </div>

    <h3>Evidências recomendadas</h3>
    <ol>
      <li><strong>Primária:</strong> brinco físico ou registro oficial equivalente.</li>
      <li><strong>Secundária:</strong> ficha individual, histórico reprodutivo, foto identificada,
        registro de compra/venda ou confirmação do responsável pelo rebanho.</li>
      <li><strong>Auditoria:</strong> anotar a fonte usada, a decisão, a data e quem conferiu.</li>
    </ol>
    <div class="callout warning">
      Um arquivo parcial atualiza somente os animais que identifica. Campo ausente não
      significa valor vazio, e animal não listado não significa animal removido.
    </div>
  </section>

  <section class="page section">
    <h2>2. Ordem recomendada de resolução</h2>
    <table>
      <thead><tr><th style="width:13mm">Ordem</th><th>Grupo</th><th>Risco</th><th>Decisão esperada</th></tr></thead>
      <tbody>
        <tr><td>1</td><td>30 DEL vazios</td><td>Indicador reprodutivo inconsistente</td><td>Confirmar último parto ou corrigir situação com evidência. Única verificação obrigatória.</td></tr>
        <tr><td>—</td><td>13 nomes divergentes</td><td>Observação cadastral, não identidade</td><td>O brinco já confirmou a identidade deste animal; confirmar o nome oficial é uma ação cadastral separada, não um bloqueio.</td></tr>
        <tr><td>—</td><td>27 coincidências por nome</td><td>Fusão indevida se agido sem evidência</td><td>Não agir; investigar somente se uma futura decisão de fusão exigir.</td></tr>
        <tr><td>—</td><td>141 sem nova medição</td><td>Perda de histórico</td><td>Preservar automaticamente; nenhuma classificação manual é necessária.</td></tr>
      </tbody>
    </table>
    <h3>Critério de encerramento</h3>
    <p>
      Os 30 alertas de DEL são a única verificação obrigatória desta baseline: só estão
      resolvidos quando a decisão possui evidência e foi revisada.
      As divergências de nome e as coincidências de nome são observações e não bloqueiam a migração.
      Os 141 cadastros preservados não se tornam pendências apenas por aparecerem nesta lista.
    </p>
    <h3>Como aplicar as decisões</h3>
    <ul>
      <li>Faça uma cópia da baseline antes de qualquer alteração.</li>
      <li>Aplique mudanças em lote somente após concluir e revisar a planilha de decisões.</li>
      <li>Valide identificadores únicos e totais de animais e medições depois da alteração.</li>
      <li>Guarde este relatório preenchido como evidência do processo.</li>
    </ul>
    <div class="callout">
      <strong>Princípio:</strong> em dúvida, preservar. É mais seguro manter um cadastro
      pendente do que apagar ou fundir históricos que depois não possam ser reconstruídos.
    </div>
  </section>

  <section class="page section">
    <h2>3. Decisões de negócio e contrato dos arquivos</h2>
    <p class="lead">
      Estas perguntas definem o comportamento esperado do produto. A orientação técnica
      registra a opção mais segura; o argumento explica o problema que ela evita. A decisão
      final e seu responsável devem ser confirmados pelo negócio antes da migração.
    </p>
    <table class="decision-table">
      <thead>
        <tr>
          <th style="width:31mm">Pergunta</th>
          <th style="width:45mm">Orientação técnica</th>
          <th>Argumento</th>
          <th style="width:25mm">Decisão final</th>
          <th style="width:25mm">Responsável/data</th>
        </tr>
      </thead>
      <tbody>{project_decision_rows}</tbody>
    </table>
  </section>

  <section class="page section">
    <h2>4. Divergências de nome — 13 casos, não bloqueiam a migração</h2>
    <p class="lead">
      Nestes 13 casos o brinco já confirmou a identidade deste animal — o nome do PDF
      apenas difere do nome cadastrado na base. Isto não é um conflito de identidade e
      não exige decisão antes da migração. É uma observação cadastral opcional: se a
      grafia oficial for confirmada, a atualização do nome deve ser uma ação separada e
      auditada, nunca automática.
    </p>
    <table>
      <thead>
        <tr><th class="check">OK</th><th style="width:19mm">Brinco</th><th>Nome no PDF</th><th>Nome atual na base</th><th style="width:66mm">Conferência (opcional)</th></tr>
      </thead>
      <tbody>{divergence_rows}</tbody>
    </table>
    <div class="callout warning">
      <strong>Vale conferir com mais atenção:</strong> DENGOSA/CABELO DE FOGO,
      CODORNA/BOEMIA, MALHADA/MACHADA e CRAUNA/PAUNA não parecem apenas variações
      ortográficas. Mesmo assim, o brinco já é a identidade válida; a conferência serve
      só para decidir se o nome cadastrado deve ser atualizado.
    </div>
  </section>

  <section class="page section">
    <h2>5. DEL vazio em animais em lactação — 30 casos</h2>
    <p class="lead">
      Esses animais têm brinco e estão marcados como “Em lactação”, mas não possuem DEL.
      Verifique a data do último parto. Se não houve parto compatível, confirme se a situação
      está errada; não invente um DEL apenas para eliminar o alerta.
    </p>
    <table>
      <thead>
        <tr><th class="check">OK</th><th style="width:18mm">Brinco</th><th style="width:15mm">Número</th><th>Animal</th><th style="width:24mm">Situação</th><th style="width:67mm">Conferência</th></tr>
      </thead>
      <tbody>{warning_rows}</tbody>
    </table>
  </section>

  <section class="page section">
    <h2>6. Coincidências de nome não conclusivas — 27 pares</h2>
    <p class="lead">
      Estes pares têm nomes iguais ou próximos, mas identificadores diferentes. Eles não
      são conflitos nem duplicidades presumidas. Permanecem separados e só precisam ser
      investigados se surgir uma razão concreta para relacioná-los.
    </p>
    <table>
      <thead>
        <tr><th>Registro legado</th><th>Registro do relatório</th><th style="width:82mm">Tratamento</th></tr>
      </thead>
      <tbody>{candidate_rows}</tbody>
    </table>
    <div class="callout danger">
      <strong>BOLINHA demonstra por que nome não identifica:</strong> os registros legados
      19 e 626 têm o mesmo nome do registro 956. Os três permanecem separados; uma eventual
      fusão exigirá brinco e outra evidência independente.
    </div>
  </section>

  <section class="page section">
    <h2>7. Cadastros preservados sem nova medição neste arquivo — 141</h2>
    <p class="lead">
      Esta lista é informativa e não exige classificação manual. O arquivo pode representar
      outro grupo de gado; por isso, a medição e o histórico anteriores continuam válidos.
      Cada cadastro permanecerá inalterado até uma atualização futura identificá-lo
      explicitamente.
    </p>
    <div class="callout">
      <strong>Nenhuma ação:</strong> não zerar produção, não alterar situação e não inferir
      venda, descarte, óbito ou duplicidade a partir da ausência neste arquivo.
    </div>
    <table>
      <thead>
        <tr>
          <th style="width:22mm">Número</th><th>Animal</th>
          <th style="width:20mm">Lote</th><th style="width:21mm">Situação</th>
          <th style="width:12mm">Leit.</th><th style="width:72mm">Tratamento</th>
        </tr>
      </thead>
      <tbody>{legacy_rows}</tbody>
    </table>
  </section>

  <section class="page section">
    <h2>8. Aprovação e rastreabilidade</h2>
    <p class="lead">
      Use esta página depois que todos os itens estiverem preenchidos. Conte novamente os
      itens pendentes e registre qualquer exceção antes de aplicar as decisões na base.
    </p>
    <table>
      <thead><tr><th>Controle</th><th style="width:25mm">Resolvidos</th><th style="width:25mm">Pendentes</th><th>Observações</th></tr></thead>
      <tbody>
        <tr><td>Alertas de DEL (30) — obrigatório</td><td></td><td></td><td class="write-cell"></td></tr>
        <tr><td>Decisões de contrato (14 tópicos)</td><td></td><td></td><td class="write-cell"></td></tr>
        <tr><td>Divergências de nome revisadas quando aplicável (13, opcional)</td><td></td><td></td><td class="write-cell"></td></tr>
        <tr><td>Coincidências investigadas quando aplicável (27, opcional)</td><td></td><td></td><td class="write-cell"></td></tr>
      </tbody>
    </table>
    <div class="signoff">
      <div><div class="sign-line"></div><p>Responsável pela conferência · nome e data</p></div>
      <div><div class="sign-line"></div><p>Revisor · nome e data</p></div>
    </div>
    <div class="callout warning">
      Os 30 alertas de DEL são a única verificação obrigatória desta baseline. A
      migração para PostgreSQL só deve ser declarada reconciliada depois que eles e
      as decisões de contrato forem aprovados. As divergências de nome e as
      coincidências de nome são observações e não bloqueiam a migração; os 141
      cadastros informativos permanecem preservados sem exigir ação.
    </div>
    <p class="footer-note">
      Fontes: {e(CANONICAL.relative_to(ROOT))} e {e(REPORT_PDF.relative_to(ROOT))}.
      Documento gerado automaticamente; os campos de decisão permanecem deliberadamente
      em branco para conferência humana.
    </p>
  </section>
</body>
</html>
"""


def main() -> int:
    content = build_html()
    OUTPUT.write_text(content, encoding="utf-8", newline="\n")
    print(f"generated={OUTPUT}")
    print("legacy_only=141 divergences=13 del_warnings=30 candidate_pairs=27")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
