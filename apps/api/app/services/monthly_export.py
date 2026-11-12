import io
from openpyxl import Workbook
from openpyxl.styles import Font
from app.schemas.monthly_report import MonthlyReport
from app.services.production_export import _text

STATUS = {'positive': 'Positivo (estimado)', 'negative': 'Negativo (estimado)', 'balanced': 'Equilibrado (estimado)', 'insufficient': 'Dados insuficientes'}


def build_monthly_workbook(report: MonthlyReport) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = 'Fechamento mensal'
    columns = ['Mês', 'Até', 'Dias do período', 'Dias com coleta', 'Leituras', 'Animais distintos',
        'Litros registrados', 'Média L/dia de coleta', 'Média L/vaca por leitura', 'Litros estimados no período',
        'Receita estimada (R$)', 'Alimentação estimada (R$)', 'Resultado após alimentação (R$)', 'Margem (%)',
        'Situação', 'Mês em andamento', 'Dias com valores atuais simulados', 'Observações']
    sheet.append(columns)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for row_number, row in enumerate(report.months, 2):
        values = [row.month, row.end, row.elapsed_days, row.reading_days, row.reading_count, row.animals_read,
            row.recorded_liters, row.average_liters_per_collection, row.average_liters_per_animal_reading, row.estimated_liters,
            row.estimated_revenue, row.estimated_feed_cost, row.estimated_result, row.margin_pct,
            STATUS[row.status], 'Sim' if row.in_progress else 'Não', row.assumed_days, ' '.join(row.warnings)]
        for column, value in enumerate(values, 1):
            cell = sheet.cell(row_number, column)
            if isinstance(value, str):
                _text(cell, value)
            elif value is not None:
                cell.value = value
                if column == 2:
                    cell.number_format = 'dd/mm/yyyy'
                elif 7 <= column <= 14:
                    cell.number_format = '#,##0.00'
    sheet.freeze_panes = 'A2'
    sheet.auto_filter.ref = sheet.dimensions
    for column in sheet.columns:
        sheet.column_dimensions[column[0].column_letter].width = 25
    sheet.column_dimensions['R'].width = 90
    method = workbook.create_sheet('Metodologia')
    for index, (label, value) in enumerate([
        ('Fazenda', report.farm_name), ('Gerado em', report.generated_on.isoformat()),
        ('Período', f'{report.start_month} a {report.end_month}'),
        ('Simulação com valores atuais autorizada', 'Sim' if report.current_values_simulation else 'Não'),
        ('Método', report.method),
        ('Limite', 'Resultado após alimentação dos lotes cadastrados. Não representa lucro líquido; outras despesas não estão incluídas.'),
        ('Dados ausentes', 'Células financeiras vazias significam dados insuficientes, nunca custo ou receita zero.'),
        ('Comparação', 'Melhor e pior mês consideram meses encerrados com base financeira suficiente. O resultado continua estimado.'),
        ('Cobertura', 'A produção estimada não adiciona animais ausentes das coletas. Confira variações na quantidade de animais por coleta.'),
    ], 1):
        _text(method.cell(index, 1), label)
        _text(method.cell(index, 2), value)
    method.column_dimensions['A'].width = 45
    method.column_dimensions['B'].width = 130
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()
