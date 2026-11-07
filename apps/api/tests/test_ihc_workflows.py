"""As tarefas aprovadas no protótipo funcionam com autenticação e banco reais."""

from tests.test_multi_producer import api, db, mail, producer, headers
from tests.pg_support import one


def configured_farm(api, mail):
    owner = producer(api, mail)
    configured = api.patch(
        "/api/farms/current",
        headers=headers(owner),
        json={
            "name": "Fazenda da revisão",
            "timezone": "America/Recife",
            "lot_settings": [
                {"name": "Ordenha principal", "kind": "diet"},
                {"name": "Ordenha nova", "kind": "diet"},
                {"name": "Bezerreiro", "kind": "management"},
            ],
            "milk_price_per_liter": 2.5,
        },
    )
    assert configured.status_code == 200, configured.text
    return owner


def create_cow(api, owner):
    response = api.post(
        "/api/animals",
        headers=headers(owner),
        json={"brinco": "027", "name": "Mimosa", "lote": "Ordenha principal", "lote_valid_from": "2020-01-01"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_manual_destinations_are_configured_and_do_not_guess_a_group(api, db, mail):
    owner = configured_farm(api, mail)
    invalid = api.post("/api/animals", headers=headers(owner), json={"name": "Erro", "lote": "Ordenha pricipal"})
    assert invalid.status_code == 422
    assert one("SELECT count(*) FROM animals")[0][0] == 0
    cow = create_cow(api, owner)
    path = f"/api/animals/{cow['id']}/lote"
    for payload in [
        {"lote": "Ordenha nvoa", "valid_from": "2020-01-02"},
        {"lote": "Bezerreiro", "kind": "diet", "valid_from": "2020-01-02"},
    ]:
        assert api.post(path, headers=headers(owner), json=payload).status_code == 422
    untouched = api.get(f"/api/animals/{cow['id']}", headers=headers(owner)).json()
    assert untouched["lote_atual"] == "Ordenha principal"
    assert untouched["grupo_manejo"] is None
    assert len(untouched["historico_lotes"]) == 1
    moved = api.post(path, headers=headers(owner), json={"lote": "  ORDENHA NOVA  ", "valid_from": "2020-01-02"})
    assert moved.status_code == 200, moved.text
    assert moved.json()["lote_atual"] == "Ordenha nova"
    assert moved.json()["grupo_manejo"] is None


def test_missing_diet_is_distinct_from_a_registered_zero_and_cost_updates(api, db, mail):
    owner = configured_farm(api, mail)
    cow = create_cow(api, owner)
    entered = api.post("/api/production", headers=headers(owner), json={"animal_id": cow["id"], "measured_on": "2026-01-01", "producao": 20})
    assert entered.status_code == 201, entered.text
    initial = api.get("/api/dashboard", headers=headers(owner)).json()
    assert initial["missing_diet_lots"] == ["Ordenha principal"]
    assert initial["total_revenue"] == 50
    assert initial["total_profit"] is None
    assert initial["lots"][0]["profit"] is None
    supply = api.post("/api/supplies", headers=headers(owner), json={"name": "Silagem", "price_per_kg": 0.5}).json()
    path = f"/api/supplies/{supply['id']}/diet"
    for destination in ("Ordenha pricipal", "Bezerreiro"):
        assert api.put(path, headers=headers(owner), json={"lote": destination, "kg_per_day": 20}).status_code == 422
    assert one("SELECT count(*) FROM supply_diets")[0][0] == 0
    zero = api.put(path, headers=headers(owner), json={"lote": "ORDENHA PRINCIPAL", "kg_per_day": 0})
    assert zero.status_code == 200, zero.text
    known_zero = api.get("/api/dashboard", headers=headers(owner)).json()
    assert known_zero["missing_diet_lots"] == []
    assert known_zero["total_feed_cost"] == 0
    assert known_zero["total_profit"] == 50
    changed = api.put(path, headers=headers(owner), json={"lote": "Ordenha principal", "kg_per_day": 60})
    assert changed.status_code == 200, changed.text
    panel = api.get("/api/dashboard", headers=headers(owner)).json()
    assert panel["total_feed_cost"] == 30
    assert panel["total_profit"] == 20
    assert api.get("/api/supplies", headers=headers(owner)).json()[0]["diets"] == [{"lote": "Ordenha principal", "kg_per_day": 60}]
