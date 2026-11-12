import { expect, test } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { daysAgo, login, openArea, runTag } from './seed';

test('fechamento mensal real, exportação e uso no celular', async ({ page, request }) => {
  test.setTimeout(120_000);
  const tag = runTag();
  const email = `mensal${tag}@monthly.test`;
  const password = 'pasto verde para fechar o mes';
  const month = daysAgo(70).slice(0, 7);
  const since = `${month}-01`;
  const created = await request.post('/api/auth/register', { data: { email, password, producer_name: 'Produtor mensal', farm_name: `Fazenda mensal ${tag}` } });
  expect(created.status()).toBe(202);
  const found = await request.get(`http://localhost:8025/api/v1/search?query=${encodeURIComponent(`to:${email}`)}`);
  const mail = await (await request.get(`http://localhost:8025/api/v1/message/${(await found.json()).messages[0].ID}`)).json();
  const token = new URL(/https?:\/\/\S+/.exec(mail.Text)![0]).searchParams.get('token');
  expect((await request.post('/api/auth/verify', { data: { token } })).ok()).toBeTruthy();
  const identity = await (await request.post('/api/auth/login', { data: { email, password } })).json();
  const headers = { Authorization: `Bearer ${identity.access_token}` };
  expect((await request.patch('/api/farms/current', { headers, data: { name: `Fazenda mensal ${tag}`, timezone: 'America/Recife', lot_settings: [{ name: 'Ordenha', kind: 'diet' }], milk_price_per_liter: 2 } })).ok()).toBeTruthy();
  expect((await request.patch('/api/farms/current/milk-price', { headers, data: { milk_price_per_liter: 2, effective_on: since } })).ok()).toBeTruthy();
  const cow = await (await request.post('/api/animals', { headers, data: { brinco: '027', name: 'Mimosa mensal', lote: 'Ordenha', lote_valid_from: since } })).json();
  const supply = await (await request.post('/api/supplies', { headers, data: { name: 'Silagem mensal', price_per_kg: 1 } })).json();
  expect((await request.patch(`/api/supplies/${supply.id}`, { headers, data: { price_per_kg: 1, effective_on: since } })).ok()).toBeTruthy();
  expect((await request.put(`/api/supplies/${supply.id}/diet`, { headers, data: { lote: 'Ordenha', kg_per_day: 10, effective_on: since } })).ok()).toBeTruthy();
  expect((await request.post('/api/production', { headers, data: { animal_id: cow.id, measured_on: `${month}-10`, producao: 20 } })).ok()).toBeTruthy();
  await login(page, email, password);
  await page.getByRole('link', { name: 'Relatório mensal', exact: true }).click();
  await expect(page).toHaveURL(/\/relatorios$/);
  await page.getByLabel('Mês inicial').fill(month);
  await page.getByLabel('Mês final').fill(month);
  await expect(page.locator('.monthly-months > article')).toHaveCount(1);
  await expect(page.getByText('Positivo (estimado)', { exact: true })).toBeVisible();
  const days = new Date(Number(month.slice(0, 4)), Number(month.slice(5)), 0).getDate();
  const payload = await (await request.get(`/api/reports/monthly?inicio=${month}&fim=${month}`, { headers })).json();
  expect(payload.months[0].recorded_liters).toBe(20);
  expect(payload.months[0].estimated_result).toBe(days * 30);
  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Baixar relatório (XLSX)' }).click();
  expect((await download).suggestedFilename()).toBe(`relatorio-mensal-${month}-a-${month}.xlsx`);
  for (const theme of ['light', 'dark'] as const) {
    for (const width of [320, 390]) {
      await page.emulateMedia({ colorScheme: theme, reducedMotion: 'reduce' });
      await page.setViewportSize({ width, height: 844 });
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBeTruthy();
      expect(await page.getByLabel('Mês inicial').evaluate(input => input.clientWidth)).toBeGreaterThan(200);
      const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']).analyze();
      expect(results.violations.filter(v => v.impact === 'serious' || v.impact === 'critical')).toEqual([]);
    }
  }
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Relatório mensal', exact: true })).toBeVisible();

  // Vigências podem ser informadas pela interface e mudam somente o período devido.
  await openArea(page, 'Insumos');
  await page.getByLabel('Preço do leite válido a partir de').fill(since);
  await page.getByLabel('Preço por litro (R$)', { exact: true }).fill('3');
  await page.getByRole('button', { name: 'Salvar preço do leite' }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Preço do leite salvo' })).toBeVisible();
  await expect(page.getByLabel('Preço por litro (R$)', { exact: true })).toHaveValue('2');
  await page.getByRole('button', { name: 'Definir dieta', exact: true }).click();
  await page.getByLabel('Quantidade diária para o lote inteiro (kg)').fill('15');
  await page.getByLabel('Dieta válida a partir de').fill(since);
  await page.getByRole('button', { name: 'Salvar dieta', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Dieta de Silagem mensal salva' })).toBeVisible();
  await page.getByRole('button', { name: 'Alterar preço', exact: true }).click();
  await page.getByLabel('Novo preço por kg — Silagem mensal', { exact: true }).fill('2');
  await page.getByLabel('Preço do insumo válido a partir de').fill(since);
  await page.getByRole('button', { name: 'Salvar preço', exact: true }).click();
  await expect(page.getByLabel('Novo preço por kg — Silagem mensal', { exact: true })).toHaveCount(0);
  const revised = await (await request.get(`/api/reports/monthly?inicio=${month}&fim=${month}`, { headers })).json();
  expect(revised.months[0].estimated_revenue).toBe(days * 60);
  expect(revised.months[0].estimated_feed_cost).toBe(days * 30);
  expect(revised.months[0].estimated_result).toBe(days * 30);
});
