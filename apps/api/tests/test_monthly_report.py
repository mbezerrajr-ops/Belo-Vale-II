"""Fechamento mensal com banco real, vigências, isolamento e exportação."""
import io
from datetime import date
from unittest.mock import patch
import pytest
from openpyxl import load_workbook
from tests.pg_support import api, db, auth, make_farm, make_user, make_animal, one


@pytest.fixture
def scenario(api, db):
    farm = make_farm('Fazenda mensal')
    _, token = make_user('admin')
    cow = make_animal(farm, brinco='027', name='Mimosa', lote='LOTE 1', lot_since=date(2024, 1, 1))
    with patch('app.routers.dashboard.farm_today', return_value=date(2024, 1, 1)):
        supply = api.post('/api/supplies', headers=auth(token), json={'name': 'Silagem', 'price_per_kg': 1}).json()['id']
    return farm, token, cow, supply


def reading(api, token, cow, day, liters):
    response = api.post('/api/production', headers=auth(token), json={'animal_id': cow, 'measured_on': day, 'producao': liters})
    assert response.status_code == 201, response.text


def history(api, token, supply, since='2026-01-01', milk=2, kg=10, price=1):
    for method, path, payload in [
        ('PATCH', '/api/farms/current/milk-price', {'milk_price_per_liter': milk}),
        ('PATCH', f'/api/supplies/{supply}', {'price_per_kg': price}),
        ('PUT', f'/api/supplies/{supply}/diet', {'lote': 'LOTE 1', 'kg_per_day': kg}),
    ]:
        response = api.request(method, path, headers=auth(token), json={**payload, 'effective_on': since})
        assert response.status_code == 200, response.text


def report(api, token, start='2026-01', end='2026-02', simulate=False, today=date(2026, 3, 10)):
    with patch('app.routers.monthly_report.farm_today', return_value=today):
        response = api.get('/api/reports/monthly', headers=auth(token), params={'inicio': start, 'fim': end, 'simular_atuais': str(simulate).lower()})
    assert response.status_code == 200, response.text
    return response.json()


def test_monthly_average_profit_loss_and_adjacent_comparison(api, scenario):
    _, token, cow, supply = scenario
    history(api, token, supply)
    reading(api, token, cow, '2026-01-10', 10)
    reading(api, token, cow, '2026-01-20', 20)
    reading(api, token, cow, '2026-02-10', 2)
    body = report(api, token)
    jan, feb = body['months']
    assert jan['recorded_liters'] == 30
    assert jan['reading_days'] == 2
    assert jan['average_liters_per_collection'] == 15
    assert jan['average_liters_per_animal_reading'] == 15
    assert jan['estimated_liters'] == 465
    assert jan['estimated_revenue'] == 930
    assert jan['estimated_feed_cost'] == 310
    assert jan['estimated_result'] == 620
    assert jan['margin_pct'] == 66.67
    assert jan['status'] == 'positive'
    assert feb['estimated_result'] == -168
    assert feb['status'] == 'negative'
    assert feb['result_change'] == -788
    assert feb['production_change_pct'] == -87.96
    assert body['best_month'] == '2026-01'
    assert body['worst_month'] == '2026-02'
    assert body['positive_months'] == body['negative_months'] == 1


def test_no_backward_projection_and_explicit_simulation(api, scenario):
    _, token, cow, supply = scenario
    history(api, token, supply, since='2026-02-01')
    reading(api, token, cow, '2026-01-10', 10)
    unknown = report(api, token)['months'][0]
    assert unknown['estimated_result'] is None
    assert unknown['estimated_revenue'] is None
    assert unknown['status'] == 'insufficient'
    simulated = report(api, token, simulate=True)['months'][0]
    assert simulated['estimated_result'] == 310
    assert simulated['assumed_days'] == 31
    assert any('Simulação' in message for message in simulated['warnings'])


def test_vigencies_inside_month_and_backdating_preserves_current_values(api, scenario):
    farm, token, cow, supply = scenario
    history(api, token, supply, since='2026-01-16', milk=3, kg=20, price=2)
    history(api, token, supply, since='2026-01-01', milk=2, kg=10, price=1)
    reading(api, token, cow, '2026-01-10', 10)
    jan = report(api, token)['months'][0]
    assert jan['estimated_revenue'] == 10 * (15 * 2 + 16 * 3)
    assert jan['estimated_feed_cost'] == 15 * 10 * 1 + 16 * 20 * 2
    assert api.get('/api/farms/current', headers=auth(token)).json()['milk_price_per_liter'] == 3
    current = api.get('/api/supplies', headers=auth(token)).json()[0]
    assert current['price_per_kg'] == 2
    assert current['diets'][0]['kg_per_day'] == 20


def test_missing_month_leap_year_zero_diet_and_current_month_are_distinct(api, scenario):
    _, token, cow, supply = scenario
    history(api, token, supply, since='2024-01-01', kg=0, price=0)
    reading(api, token, cow, '2024-02-10', 0)
    body = report(api, token, '2024-01', '2024-03', today=date(2024, 3, 10))
    jan, feb, mar = body['months']
    assert jan['reading_days'] == 0 and jan['estimated_liters'] is None
    assert jan['status'] == 'insufficient'
    assert feb['elapsed_days'] == 29
    assert feb['estimated_result'] == 0
    assert feb['status'] == 'balanced'
    assert feb['margin_pct'] is None
    assert mar['in_progress'] is True and mar['elapsed_days'] == 10
    assert body['best_month'] == body['worst_month'] == '2024-02'


def test_historical_readings_of_exited_animals_and_superseded_readings(api, scenario):
    _, token, cow, supply = scenario
    history(api, token, supply)
    reading(api, token, cow, '2026-01-10', 10)
    old = one('SELECT id FROM official_measurements WHERE animal_id=:a', a=cow)[0][0]
    changed = api.post(f'/api/production/{old}/correction', headers=auth(token), json={'producao': 20, 'reason': 'Conferido no papel'})
    assert changed.status_code == 201, changed.text
    one("UPDATE animals SET exited_on='2026-02-01',exit_reason='venda' WHERE id=:a", a=cow)
    jan = report(api, token)['months'][0]
    assert jan['recorded_liters'] == 20 and jan['reading_count'] == 1


def test_invalid_periods_and_future_vigency_are_rejected(api, scenario):
    _, token, _, supply = scenario
    for start, end in [('2026-02', '2026-01'), ('2020-01', '2026-01'), ('2026-01', '2027-01'), ('2026-13', '2026-01')]:
        with patch('app.routers.monthly_report.farm_today', return_value=date(2026, 3, 10)):
            response = api.get('/api/reports/monthly', headers=auth(token), params={'inicio': start, 'fim': end})
        assert response.status_code == 422
    for path, payload in [('/api/farms/current/milk-price', {'milk_price_per_liter': 2}), (f'/api/supplies/{supply}/diet', {'lote': 'LOTE 1', 'kg_per_day': 2})]:
        response = api.request('PUT' if path.endswith('/diet') else 'PATCH', path, headers=auth(token), json={**payload, 'effective_on': '2099-01-01'})
        assert response.status_code == 422


def test_export_matches_screen_and_operator_cannot_export(api, scenario):
    farm, token, cow, supply = scenario
    history(api, token, supply)
    reading(api, token, cow, '2026-01-10', 10)
    one('UPDATE farms SET name=:n WHERE id=:f', n='=1+1', f=farm)
    with patch('app.routers.monthly_report.farm_today', return_value=date(2026, 3, 10)):
        response = api.get('/api/reports/monthly/export', headers=auth(token), params={'inicio': '2026-01', 'fim': '2026-02'})
    assert response.status_code == 200, response.text
    book = load_workbook(io.BytesIO(response.content), data_only=False)
    assert book['Fechamento mensal']['M2'].value == 310
    assert book['Fechamento mensal']['M3'].value is None
    assert book['Metodologia']['B1'].value == '=1+1'
    assert book['Metodologia']['B1'].data_type == 's'
    assert one("SELECT count(*) FROM audit_events WHERE action='monthly_report_exported'")[0][0] == 1
    _, operator = make_user('operator')
    assert api.get('/api/reports/monthly/export', headers=auth(operator), params={'inicio': '2026-01', 'fim': '2026-02'}).status_code == 403
    assert report(api, operator)['months'][0]['recorded_liters'] == 10


def test_other_farm_header_never_reads_another_producer(api, db):
    from tests.test_multi_producer import producer, headers
    from app.services.account_mail import MemoryMailer, get_mailer
    mail = MemoryMailer()
    api.app.dependency_overrides[get_mailer] = lambda: mail
    a = producer(api, mail, 'ana.month@example.org')
    b = producer(api, mail, 'bia.month@example.org', name='Fazenda Bia')
    cow = make_animal(b['farm']['id'], brinco='042', name='Vaca da Bia', lote='LOTE 1', lot_since=date(2024, 1, 1))
    reading(api, b['token'], cow, '2026-01-10', 42)
    response = api.get('/api/reports/monthly', headers=headers(a, b['farm']['id']), params={'inicio': '2026-01', 'fim': '2026-02'})
    assert response.status_code == 404
    own = report(api, a['token'])
    assert own['farm_name'] == a['farm']['name']
    assert sum(row['recorded_liters'] for row in own['months']) == 0
    assert report(api, b['token'])['months'][0]['recorded_liters'] == 42
