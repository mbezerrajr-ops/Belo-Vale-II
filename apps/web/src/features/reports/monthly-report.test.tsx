import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { MonthlyReportPage } from './MonthlyReportPage';
import type { MonthlyReport, MonthlyResult } from '../../api/types';
import * as api from '../../api/client';

vi.mock('../../api/client', () => ({ getMonthlyReport: vi.fn(), downloadMonthlyReport: vi.fn() }));
vi.mock('../../ui/dates', async original => ({ ...(await original<typeof import('../../ui/dates')>()), farmToday: () => '2026-03-10' }));
const client = vi.mocked(api);
function month(overrides: Partial<MonthlyResult> = {}): MonthlyResult {
  return { month: '2026-01', start: '2026-01-01', end: '2026-01-31', elapsed_days: 31, calendar_days: 31, in_progress: false,
    reading_days: 2, reading_count: 2, animals_read: 1, animals_per_collection_min: 1, animals_per_collection_max: 1,
    recorded_liters: 30, average_liters_per_collection: 15, average_liters_per_animal_reading: 15, estimated_liters: 465,
    estimated_revenue: 930, estimated_feed_cost: 310, estimated_result: 620, margin_pct: 66.67,
    production_change_pct: null, result_change: null, status: 'positive', milk_price_days: 31, diet_days: 31, assumed_days: 0,
    warnings: ['Estimativa baseada em dois dias de coleta.'], ...overrides };
}
function report(overrides: Partial<MonthlyReport> = {}): MonthlyReport {
  return { generated_on: '2026-03-10', farm_name: 'Fazenda teste', start_month: '2026-01', end_month: '2026-03',
    current_values_simulation: false, method: 'Média dos totais das coletas × dias do período.',
    months: [month()], best_month: '2026-01', worst_month: '2026-01', positive_months: 1, negative_months: 0, balanced_months: 0, insufficient_months: 0, ...overrides };
}
beforeEach(() => { vi.resetAllMocks(); client.getMonthlyReport.mockResolvedValue(report()); client.downloadMonthlyReport.mockResolvedValue(); });
afterEach(cleanup);

it('mostra registrados, estimados e escopo sem chamar saldo de lucro líquido', async () => {
  render(<MonthlyReportPage token="token" canExport />);
  expect(await screen.findByText('Positivo (estimado)')).toBeVisible();
  expect(screen.getByText('Litros registrados')).toBeVisible();
  expect(screen.getByText('Litros estimados no período')).toBeVisible();
  expect(screen.getByText(/não representam lucro líquido/)).toBeVisible();
  expect(client.getMonthlyReport).toHaveBeenCalledWith('token', '2026-01', '2026-03', false);
  fireEvent.click(screen.getByRole('button', { name: 'Baixar relatório (XLSX)' }));
  await waitFor(() => expect(client.downloadMonthlyReport).toHaveBeenCalledWith('token', '2026-01', '2026-03', false));
});

it('não exibe ausência de base como saldo zero e identifica mês parcial', async () => {
  client.getMonthlyReport.mockResolvedValue(report({ months: [month({ month: '2026-03', in_progress: true, elapsed_days: 10, reading_days: 0,
    status: 'insufficient', estimated_result: null, estimated_revenue: null, estimated_feed_cost: null, estimated_liters: null })], best_month: null, worst_month: null }));
  render(<MonthlyReportPage token="token" canExport={false} />);
  expect(await screen.findByText('Dados insuficientes')).toBeVisible();
  expect(screen.getByText(/considera 10 de 31 dias/)).toBeVisible();
  expect(screen.queryByRole('button', { name: 'Baixar relatório (XLSX)' })).not.toBeInTheDocument();
  expect(screen.queryByText(/R\$\s*0,00/)).not.toBeInTheDocument();
});

it('simulação exige escolha explícita e o arquivo segue a mesma base', async () => {
  render(<MonthlyReportPage token="token" canExport />);
  await screen.findByText('Positivo (estimado)');
  client.getMonthlyReport.mockResolvedValue(report({ current_values_simulation: true }));
  fireEvent.click(screen.getByRole('checkbox'));
  await screen.findByText(/Simulação habilitada/);
  expect(client.getMonthlyReport).toHaveBeenLastCalledWith('token', '2026-01', '2026-03', true);
  fireEvent.click(screen.getByRole('button', { name: 'Baixar relatório (XLSX)' }));
  await waitFor(() => expect(client.downloadMonthlyReport).toHaveBeenLastCalledWith('token', '2026-01', '2026-03', true));
});

it('não pede um intervalo inválido e bloqueia exportação de um resultado antigo', async () => {
  render(<MonthlyReportPage token="token" canExport />);
  await screen.findByText('Positivo (estimado)');
  fireEvent.change(screen.getByLabelText('Mês inicial'), { target: { value: '2026-04' } });
  expect(screen.getByRole('alert')).toHaveTextContent('O mês final deve');
  expect(screen.getByRole('button', { name: 'Baixar relatório (XLSX)' })).toBeDisabled();
  expect(client.getMonthlyReport).toHaveBeenCalledTimes(1);
});

it('descarta resposta atrasada de outro intervalo', async () => {
  let resolveOld: (value: MonthlyReport) => void = () => {};
  client.getMonthlyReport.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; })).mockResolvedValue(report({ start_month: '2026-02', months: [month({ month: '2026-02', status: 'negative', estimated_result: -100 })] }));
  render(<MonthlyReportPage token="token" canExport />);
  fireEvent.change(screen.getByLabelText('Mês inicial'), { target: { value: '2026-02' } });
  expect(await screen.findByText('Negativo (estimado)')).toBeVisible();
  resolveOld(report());
  await waitFor(() => expect(screen.queryByText('Positivo (estimado)')).not.toBeInTheDocument());
});
