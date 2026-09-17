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
          <td class="check">☐</td>
          <td>{e(legacy_number)} / {e(legacy_name)}</td>
          <td>{e(report_tag)} / {e(report_name)}</td>
          <td class="write-cell">☐ Mesmo animal &nbsp; ☐ Diferentes<br>Evidência: ________________________</td>
        </tr>"""
        for legacy_number, legacy_name, report_tag, report_name in CANDIDATE_PAIRS
    )
    legacy_rows = "\n".join(
        f"""
        <tr>
          <td class="check">☐</td>
          <td>{e(number)}</td>
          <td>{e(name)}</td>
          <td>{e(lot)}</td>
          <td>{e(situation)}</td>
          <td>{history_count}</td>
          <td class="write-cell decision">☐ Ativo ☐ Vendido ☐ Descartado<br>☐ Óbito ☐ Duplicado ☐ Pendente</td>
        </tr>"""
        for number, name, lot, situation, history_count in legacy_only
    )

    return f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Conflitos de reconciliação manual — Belo Vale II</title>
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
      <h1>Conflitos de reconciliação para conferência manual</h1>
      <p class="subtitle">
        Guia operacional para validar cadastros antes da migração da baseline legada
        para o PostgreSQL.
      </p>
      <div class="cover-grid">
        <div class="cover-stat"><strong>30</strong>animais em lactação com DEL vazio</div>
        <div class="cover-stat"><strong>13</strong>divergências de nome por brinco</div>
        <div class="cover-stat"><strong>27</strong>possíveis duplicidades por nome</div>
        <div class="cover-stat"><strong>141</strong>animais ausentes no PDF recente</div>
      </div>
    </div>
    <div class="cover-meta">
      <strong>Versão 1.0 · {REPORT_DATE}</strong><br>
      Baseline: 401 animais · PDF: 260 registros · 260 correspondências por identificador<br>
      Estado analisado: <code>state_canonical.json</code>
    </div>
  </section>

  <section class="section">
    <h2>1. Objetivo e limite deste relatório</h2>
    <p class="lead">
      Este documento organiza os casos em que o sistema não possui evidência suficiente
      para tomar uma decisão sozinho. Ele serve como roteiro de conferência, não como
      autorização para alterar, excluir ou fundir cadastros.
    </p>
    <div class="summary-grid">
      <div class="summary-card"><strong>401</strong>animais preservados na baseline canônica</div>
      <div class="summary-card"><strong>152</strong>leituras de leite preservadas</div>
      <div class="summary-card"><strong>0</strong>cadastros criados automaticamente nesta reconciliação</div>
      <div class="summary-card"><strong>0</strong>alterações automáticas de lote ou último parto</div>
    </div>
    <div class="callout danger">
      <strong>Regra de segurança:</strong> não apagar, fundir, renomear, trocar situação
      nem preencher DEL apenas por semelhança de nome. Toda decisão precisa registrar
      fonte, responsável e data.
    </div>

    <h3>Como os conflitos aconteceram</h3>
    <p>
      O PDF recente foi comparado com a base legada. Quando existe um brinco compatível,
      ele é usado como identificador principal. O nome funciona apenas como sinal de
      conferência: grafias podem variar e nomes podem se repetir. Animais que não aparecem
      no PDF continuam preservados porque ausência não comprova venda, descarte, óbito ou
      duplicidade.
    </p>
    <div class="flow">
      <div>1. Localizar evidência</div>
      <div>2. Confirmar identidade</div>
      <div>3. Registrar decisão</div>
      <div>4. Revisar antes de aplicar</div>
    </div>

    <h3>Evidências recomendadas</h3>
    <ol>
      <li><strong>Primária:</strong> brinco físico ou registro oficial equivalente.</li>
      <li><strong>Secundária:</strong> ficha individual, histórico reprodutivo, foto identificada,
        registro de compra/venda ou confirmação do responsável pelo rebanho.</li>
      <li><strong>Auditoria:</strong> anotar a fonte usada, a decisão, a data e quem conferiu.</li>
    </ol>
    <div class="callout warning">
      Nome igual, sozinho, não comprova identidade. Para fusão ou exclusão, use o brinco
      e pelo menos mais uma evidência independente.
    </div>
  </section>

  <section class="page section">
    <h2>2. Ordem recomendada de resolução</h2>
    <table>
      <thead><tr><th style="width:13mm">Ordem</th><th>Grupo</th><th>Risco</th><th>Decisão esperada</th></tr></thead>
      <tbody>
        <tr><td>1</td><td>13 nomes divergentes</td><td>Identidade incorreta</td><td>Confirmar o nome oficial sem trocar o vínculo do brinco.</td></tr>
        <tr><td>2</td><td>30 DEL vazios</td><td>Indicador reprodutivo inconsistente</td><td>Confirmar último parto ou corrigir situação com evidência.</td></tr>
        <tr><td>3</td><td>27 pares candidatos</td><td>Duplicidade ou fusão indevida</td><td>Marcar “mesmo animal” somente com duas evidências.</td></tr>
        <tr><td>4</td><td>141 ausentes do PDF</td><td>Exclusão indevida de histórico</td><td>Classificar destino; preservar cadastro e histórico.</td></tr>
      </tbody>
    </table>
    <h3>Critério de encerramento</h3>
    <p>
      Um item só está resolvido quando a decisão é inequívoca, possui evidência registrada
      e foi revisada por outra pessoa. Caso contrário, deve permanecer como
      <span class="tag">PENDENTE</span>.
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
    <h2>3. Divergências de nome — 13 casos</h2>
    <p class="lead">
      O brinco encontrou um registro, mas o nome do PDF difere do nome da base. Confirme
      a grafia oficial e registre a evidência. O nome da base foi mantido até essa decisão.
    </p>
    <table>
      <thead>
        <tr><th class="check">OK</th><th style="width:19mm">Brinco</th><th>Nome no PDF</th><th>Nome atual na base</th><th style="width:66mm">Conferência</th></tr>
      </thead>
      <tbody>{divergence_rows}</tbody>
    </table>
    <div class="callout danger">
      <strong>Prioridade alta:</strong> DENGOSA/CABELO DE FOGO, CODORNA/BOEMIA,
      MALHADA/MACHADA e CRAUNA/PAUNA não parecem apenas variações ortográficas.
    </div>
  </section>

  <section class="page section">
    <h2>4. DEL vazio em animais em lactação — 30 casos</h2>
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
    <h2>5. Possíveis duplicidades por nome — 27 pares</h2>
    <p class="lead">
      Estes pares têm nomes iguais ou muito próximos, mas identificadores diferentes.
      A semelhança é apenas uma pista. Confirme brinco, histórico, características físicas
      e origem antes de decidir.
    </p>
    <table>
      <thead>
        <tr><th class="check">OK</th><th>Registro legado</th><th>Registro do relatório</th><th style="width:72mm">Decisão e evidência</th></tr>
      </thead>
      <tbody>{candidate_rows}</tbody>
    </table>
    <div class="callout danger">
      <strong>BOLINHA exige investigação separada:</strong> os registros legados 19 e 626
      apontam pelo nome para o mesmo registro 956. Nenhuma fusão deve ocorrer até identificar
      fisicamente qual registro, se algum, corresponde ao brinco 956.
    </div>
  </section>

  <section class="page section">
    <h2>6. Animais ausentes no PDF recente — 141 casos</h2>
    <p class="lead">
      Ausência no PDF não significa que o cadastro possa ser removido. Para cada item,
      confirme o destino e registre a evidência. Mesmo após venda, descarte ou óbito,
      preserve o histórico e altere apenas o status conforme a regra oficial.
    </p>
    <table>
      <thead>
        <tr>
          <th class="check">OK</th><th style="width:22mm">Número</th><th>Animal</th>
          <th style="width:20mm">Lote</th><th style="width:21mm">Situação</th>
          <th style="width:12mm">Leit.</th><th style="width:62mm">Classificação manual</th>
        </tr>
      </thead>
      <tbody>{legacy_rows}</tbody>
    </table>
  </section>

  <section class="page section">
    <h2>7. Aprovação e rastreabilidade</h2>
    <p class="lead">
      Use esta página depois que todos os itens estiverem preenchidos. Conte novamente os
      itens pendentes e registre qualquer exceção antes de aplicar as decisões na base.
    </p>
    <table>
      <thead><tr><th>Controle</th><th style="width:25mm">Resolvidos</th><th style="width:25mm">Pendentes</th><th>Observações</th></tr></thead>
      <tbody>
        <tr><td>Divergências de nome (13)</td><td></td><td></td><td class="write-cell"></td></tr>
        <tr><td>Alertas de DEL (30)</td><td></td><td></td><td class="write-cell"></td></tr>
        <tr><td>Pares candidatos (27)</td><td></td><td></td><td class="write-cell"></td></tr>
        <tr><td>Ausentes do PDF (141)</td><td></td><td></td><td class="write-cell"></td></tr>
      </tbody>
    </table>
    <div class="signoff">
      <div><div class="sign-line"></div><p>Responsável pela conferência · nome e data</p></div>
      <div><div class="sign-line"></div><p>Revisor · nome e data</p></div>
    </div>
    <div class="callout warning">
      A migração para PostgreSQL só deve ser declarada reconciliada depois que as decisões
      forem aplicadas em ambiente controlado, validadas e comparadas com esta ficha.
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
