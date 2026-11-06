"""Contratos de isolamento usando autenticação, PostgreSQL e permissões reais."""

from urllib.parse import urlparse, parse_qs
import re
import asyncio

import pytest
from sqlalchemy.exc import DBAPIError
from tests.pg_support import api as api, db as db, one, PASSWORD, TEST_STORAGE
from app.services.account_mail import MemoryMailer, get_mailer
from app.workers.tasks import get_extraction_dispatcher


@pytest.fixture
def mail(api):
    outbox = MemoryMailer()
    api.app.dependency_overrides[get_mailer] = lambda: outbox
    return outbox


def mail_token(mail, purpose=None):
    text = mail.messages[-1]["text"]
    url = re.search(r"https?://\S+", text).group()
    return parse_qs(urlparse(url).query)["token"][0]


def headers(identity, farm=None):
    return {
        "Authorization": f"Bearer {identity['token']}",
        **(
            {"X-Farm-ID": farm or identity["farm"]["id"]}
            if identity.get("farm")
            else {}
        ),
    }


def producer(api, mail, email="ana@example.org", name="Sítio Ana"):
    result = api.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": PASSWORD,
            "producer_name": email.split("@")[0],
            "farm_name": name,
        },
    )
    assert result.status_code == 202, result.text
    token = mail_token(mail)
    assert api.post("/api/auth/verify", json={"token": token}).status_code == 200
    login = api.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    result = {"token": login.json()["access_token"], "email": email}
    result["user"] = api.get("/api/auth/me", headers=headers(result)).json()
    result["farm"] = api.get("/api/farms", headers=headers(result)).json()[0]
    result["account"] = api.get(
        "/api/producer-accounts", headers=headers(result)
    ).json()[0]
    return result


def animal(api, person, brinco="027"):
    response = api.post(
        "/api/animals",
        headers=headers(person),
        json={"brinco": brinco, "name": "Vaca própria"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def teammate(api, owner, email="funcionario@example.org", role="operator"):
    created = api.post(
        "/api/users",
        headers=headers(owner),
        json={"email": email, "password": PASSWORD, "role": role},
    )
    assert created.status_code == 201, created.text
    login = api.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    token = login.json()["access_token"]
    changed = api.post(
        "/api/users/me/password",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "current_password": PASSWORD,
            "new_password": "bezerra no pasto",
        },
    )
    assert changed.status_code == 204, changed.text
    login = api.post(
        "/api/auth/login",
        json={"email": email, "password": "bezerra no pasto"},
    )
    return {
        "token": login.json()["access_token"],
        "email": email,
        "user": created.json(),
        "farm": owner["farm"],
        "account": owner["account"],
    }


def test_registration_verifies_contact_and_starts_with_an_empty_farm(api, db, mail):
    response = api.post(
        "/api/auth/register",
        json={
            "email": "ana@example.org",
            "password": PASSWORD,
            "producer_name": "Ana",
            "farm_name": "Sítio novo",
        },
    )
    assert response.status_code == 202
    assert "token" not in response.json()
    assert (
        api.post(
            "/api/auth/login", json={"email": "ana@example.org", "password": PASSWORD}
        ).status_code
        == 403
    )
    raw = mail_token(mail)
    assert one("SELECT token_hash FROM account_tokens")[0][0] != raw
    assert api.post("/api/auth/verify", json={"token": raw}).status_code == 200
    assert api.post("/api/auth/verify", json={"token": raw}).status_code == 400
    assert one("SELECT count(*) FROM animals")[0][0] == 0
    assert one("SELECT count(*) FROM supplies")[0][0] == 0


def test_two_producers_cannot_select_or_read_each_others_farms(api, db, mail):
    ana = producer(api, mail)
    bia = producer(api, mail, "bia@example.org", "Fazenda Bia")
    assert api.get("/api/farms", headers=headers(ana)).json() == [ana["farm"]]
    assert (
        api.get(
            "/api/farms/current", headers=headers(ana, bia["farm"]["id"])
        ).status_code
        == 404
    )
    a, b = animal(api, ana), animal(api, bia)
    assert a["brinco"] == b["brinco"]
    assert api.get(f"/api/animals/{b['id']}", headers=headers(ana)).status_code == 404
    listed = api.get("/api/animals", headers=headers(ana)).json()
    assert [row["id"] for row in listed["items"]] == [a["id"]]
    assert (
        api.get(
            "/api/measurements",
            params={"farm_id": bia["farm"]["id"]},
            headers=headers(ana),
        ).status_code
        == 404
    )


def test_producer_cannot_create_a_second_farm_or_account(api, db, mail):
    ana = producer(api, mail)
    original = api.get("/api/farms", headers=headers(ana)).json()
    assert (
        api.post(
            "/api/farms/new",
            headers=headers(ana),
            json={"producer_account_id": ana["account"]["id"], "name": "Segunda"},
        ).status_code
        == 409
    )
    assert (
        api.post(
            "/api/farms", headers=headers(ana), json={"name": "Segunda"}
        ).status_code
        == 409
    )
    assert (
        api.post(
            "/api/producer-accounts",
            headers=headers(ana),
            json={"name": "Outro produtor"},
        ).status_code
        == 409
    )
    assert api.get("/api/farms", headers=headers(ana)).json() == original
    assert (
        api.get(
            "/api/farms/current", headers={"Authorization": f"Bearer {ana['token']}"}
        ).json()["id"]
        == ana["farm"]["id"]
    )


def test_user_cannot_accept_a_second_farm_even_with_an_invitation(api, db, mail):
    ana = producer(api, mail)
    bia = producer(api, mail, "bia@example.org")
    assert (
        api.post(
            "/api/farms/current/invitations",
            headers=headers(ana),
            json={"email": bia["email"], "role": "admin"},
        ).status_code
        == 201
    )
    assert (
        api.post(
            "/api/invitations/accept",
            headers=headers(bia),
            json={"token": mail_token(mail)},
        ).status_code
        == 409
    )
    assert api.get("/api/farms", headers=headers(bia)).json() == [bia["farm"]]
    with pytest.raises(DBAPIError, match="uq_farm_membership_active_user"):
        one(
            "INSERT INTO farm_memberships(farm_id,user_id,role) VALUES (:f,:u,'admin') RETURNING farm_id",
            f=ana["farm"]["id"],
            u=bia["user"]["id"],
        )


def test_account_membership_does_not_grant_a_second_farm(api, db, mail):
    ana = producer(api, mail)
    bia = producer(api, mail, "bia@example.org")
    one(
        "INSERT INTO producer_memberships(producer_account_id,user_id,role) VALUES (:a,:u,'admin') RETURNING user_id",
        a=ana["account"]["id"],
        u=bia["user"]["id"],
    )
    assert api.get("/api/farms", headers=headers(bia)).json() == [bia["farm"]]
    assert (
        api.get("/api/animals", headers=headers(bia, ana["farm"]["id"])).status_code
        == 404
    )


def test_global_role_does_not_grant_access_to_another_producer(api, db, mail):
    ana = producer(api, mail)
    bia = producer(api, mail, "bia@example.org")
    one("UPDATE users SET role='admin' WHERE id=:u RETURNING id", u=ana["user"]["id"])
    assert (
        api.get("/api/users", headers=headers(ana, bia["farm"]["id"])).status_code
        == 404
    )
    response = api.post(
        "/api/farms/new",
        headers=headers(ana),
        json={"producer_account_id": bia["account"]["id"], "name": "Invasora"},
    )
    assert response.status_code == 403


def test_invitation_is_bound_to_email_farm_and_can_be_revoked(api, db, mail):
    ana = producer(api, mail)
    employee = teammate(api, ana)
    invited = api.post(
        "/api/farms/current/invitations",
        headers=headers(ana),
        json={"email": employee["email"], "role": "reviewer"},
    )
    assert invited.status_code == 201, invited.text
    raw = mail_token(mail)
    assert (
        api.post(
            "/api/invitations/accept", headers=headers(ana), json={"token": raw}
        ).status_code
        == 403
    )
    assert (
        api.post(
            "/api/invitations/accept", headers=headers(employee), json={"token": raw}
        ).status_code
        == 200
    )
    assert (
        api.post(
            "/api/invitations/accept", headers=headers(employee), json={"token": raw}
        ).status_code
        == 400
    )
    assert api.get("/api/animals", headers=headers(employee)).status_code == 200
    assert api.get("/api/users", headers=headers(employee)).status_code == 403
    assert (
        api.patch(
            f"/api/users/{employee['user']['id']}",
            headers=headers(ana),
            json={"is_active": False},
        ).status_code
        == 200
    )
    assert api.get("/api/animals", headers=headers(employee)).status_code == 404
    assert api.get("/api/auth/me", headers=headers(employee)).status_code == 200


def test_admin_cannot_reset_identity_from_another_producer(api, db, mail):
    ana = producer(api, mail)
    bia = producer(api, mail, "bia@example.org")
    assert (
        api.post(
            f"/api/users/{bia['user']['id']}/password-reset", headers=headers(ana)
        ).status_code
        == 404
    )


def test_recovery_is_single_use_and_revokes_sessions(api, db, mail):
    ana = producer(api, mail)
    old_cookie = api.cookies.get("bv_refresh")
    assert (
        api.post("/api/auth/forgot-password", json={"email": ana["email"]}).status_code
        == 202
    )
    raw = mail_token(mail)
    new_password = "outro capim muito bem cortado"
    result = api.post(
        "/api/auth/recover-password", json={"token": raw, "password": new_password}
    )
    assert result.status_code == 200, result.text
    assert (
        api.post(
            "/api/auth/recover-password", json={"token": raw, "password": new_password}
        ).status_code
        == 400
    )
    api.cookies.set("bv_refresh", old_cookie)
    assert api.post("/api/auth/refresh").status_code == 401
    assert (
        api.post(
            "/api/auth/login", json={"email": ana["email"], "password": new_password}
        ).status_code
        == 200
    )


def test_database_prevents_merging_animals_from_different_farms(api, db, mail):
    ana = producer(api, mail)
    bia = producer(api, mail, "bia@example.org")
    a, b = animal(api, ana), animal(api, bia)
    with pytest.raises(DBAPIError, match="fazendas diferentes"):
        one(
            "UPDATE animals SET brinco=NULL, merged_into_id=:other, merged_at=CURRENT_TIMESTAMP WHERE id=:own RETURNING id",
            own=a["id"],
            other=b["id"],
        )


def test_owner_transfer_requires_password_and_an_existing_member(api, db, mail):
    ana = producer(api, mail)
    bia = producer(api, mail, "bia@example.org")
    route = f"/api/producer-accounts/{ana['account']['id']}/transfer"
    assert (
        api.post(
            route,
            headers=headers(ana),
            json={"user_id": bia["user"]["id"], "current_password": PASSWORD},
        ).status_code
        == 404
    )
    bia = teammate(api, ana, "nova-responsavel@example.org", "reviewer")
    assert (
        api.post(
            route,
            headers=headers(ana),
            json={"user_id": bia["user"]["id"], "current_password": "wrong"},
        ).status_code
        == 403
    )
    result = api.post(
        route,
        headers=headers(ana),
        json={"user_id": bia["user"]["id"], "current_password": PASSWORD},
    )
    assert result.status_code == 200, result.text
    assert (
        one(
            "SELECT count(*) FROM producer_memberships WHERE producer_account_id=:a AND role='owner'",
            a=ana["account"]["id"],
        )[0][0]
        == 1
    )

    # O novo proprietário consegue encerrar o acesso administrativo anterior
    # sem desativar a identidade nem interferir na própria operação dele.
    members_route = f"/api/producer-accounts/{ana['account']['id']}/members"
    assert api.get(members_route, headers=headers(ana)).status_code == 403
    removed = api.delete(f"{members_route}/{ana['user']['id']}", headers=headers(bia))
    assert removed.status_code == 204, removed.text
    assert api.get("/api/animals", headers=headers(ana)).status_code == 404
    assert api.get("/api/animals", headers=headers(bia)).status_code == 200
    assert api.get("/api/auth/me", headers=headers(ana)).status_code == 200


def test_reading_capacity_is_account_scoped(api, db, mail):
    ana = producer(api, mail)
    bia = producer(api, mail, "bia@example.org")
    used = api.get(
        f"/api/producer-accounts/{ana['account']['id']}/usage", headers=headers(ana)
    )
    assert used.status_code == 200, used.text
    assert used.json()["storage_bytes"] == 0
    assert (
        api.get(
            f"/api/producer-accounts/{bia['account']['id']}/usage", headers=headers(ana)
        ).status_code
        == 403
    )


def test_custom_lots_are_scoped_to_each_producers_farm(api, db, mail):
    ana = producer(api, mail)
    bia = producer(api, mail, "bia@example.org")
    configured = api.patch(
        "/api/farms/current",
        headers=headers(ana),
        json={
            "name": "Ana",
            "timezone": "America/Manaus",
            "lot_settings": [{"name": "Ordenha azul", "kind": "diet"}],
        },
    )
    assert configured.status_code == 200, configured.text
    created = api.post(
        "/api/animals",
        headers=headers(ana),
        json={"brinco": "027", "name": "Mimosa", "lote": "Ordenha azul"},
    )
    assert created.status_code == 201, created.text
    assert api.get("/api/animals", headers=headers(bia)).json()["total"] == 0
    sheet = api.get(
        "/api/production/sheet",
        params={"measured_on": "2026-11-05"},
        headers=headers(ana),
    )
    assert sheet.status_code == 200, sheet.text
    assert sheet.json()["lotes"] == ["Ordenha azul"]
    assert (
        api.patch(
            "/api/farms/current",
            headers=headers(ana),
            json={"name": "Ana", "lot_settings": []},
        ).status_code
        == 409
    )


class Dispatcher:
    def dispatch(self, run_id):
        pass


def upload(api, identity, content):
    return api.post(
        "/api/imports",
        headers=headers(identity),
        data={"farm_id": identity["farm"]["id"]},
        files={"file": ("folha.jpg", content, "image/jpeg")},
    )


def test_media_upload_and_reprocessing_cannot_cross_farms(api, db, mail):
    ana = producer(api, mail)
    bia = producer(api, mail, "bia@example.org")
    api.app.dependency_overrides[get_extraction_dispatcher] = lambda: Dispatcher()
    content = b"\xff\xd8\xff\xe0isolated-media"
    first = upload(api, ana, content)
    second = upload(api, bia, content)
    assert first.status_code == second.status_code == 202
    import_id = first.json()["id"]
    assert api.get(f"/api/imports/{import_id}", headers=headers(bia)).status_code == 404
    assert (
        api.post(
            f"/api/imports/{import_id}/reprocess", headers=headers(bia)
        ).status_code
        == 404
    )
    assert one("SELECT count(DISTINCT object_key) FROM media_assets")[0][0] == 2
    assert upload(api, ana, content).status_code == 409


def test_one_producers_storage_limit_does_not_block_another(api, db, mail):
    ana = producer(api, mail)
    bia = producer(api, mail, "bia@example.org")
    api.app.dependency_overrides[get_extraction_dispatcher] = lambda: Dispatcher()
    one(
        "UPDATE producer_accounts SET storage_limit_bytes=1 WHERE id=:a RETURNING id",
        a=ana["account"]["id"],
    )
    content = b"\xff\xd8\xff\xe0isolated-media"
    assert upload(api, ana, content).status_code == 409
    assert upload(api, bia, content).status_code == 202


def test_worker_rechecks_membership_before_reading(api, db, mail):
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from sqlalchemy.pool import NullPool
    from pg_support import database_url
    from app.services.media_reading import (
        read_upload_into_proposals,
        UnknownSenderError,
    )
    from app.services.event_extraction import FakeEventExtractor

    ana = producer(api, mail)
    bia = teammate(api, ana)
    api.app.dependency_overrides[get_extraction_dispatcher] = lambda: Dispatcher()
    uploaded = api.post(
        "/api/imports",
        headers=headers(bia, ana["farm"]["id"]),
        data={"farm_id": ana["farm"]["id"]},
        files={"file": ("folha.jpg", b"\xff\xd8\xff\xe0pending", "image/jpeg")},
    )
    assert uploaded.status_code == 202, uploaded.text
    run_id = one(
        "SELECT r.id FROM extraction_runs r JOIN media_assets m ON m.id=r.media_asset_id WHERE m.import_id=:i",
        i=uploaded.json()["id"],
    )[0][0]
    api.patch(
        f"/api/users/{bia['user']['id']}",
        headers=headers(ana),
        json={"is_active": False},
    )

    async def scenario():
        engine = create_async_engine(database_url(), poolclass=NullPool)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                with pytest.raises(UnknownSenderError):
                    await read_upload_into_proposals(
                        session,
                        TEST_STORAGE,
                        {"photo": lambda: FakeEventExtractor()},
                        extraction_run_id=run_id,
                    )
        finally:
            await engine.dispose()

    asyncio.run(scenario())
    assert one("SELECT status,failure_code FROM extraction_runs WHERE id=:i", i=run_id)[
        0
    ] == ("failed", "sender_unknown")
    assert one("SELECT count(*) FROM event_proposals")[0][0] == 0


def test_selective_recovery_is_a_new_copy_and_preserves_other_producers(api, db, mail):
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from sqlalchemy.pool import NullPool
    from pg_support import database_url
    from app.services.farm_recovery import farm_snapshot, recover_farm
    from uuid import UUID

    ana = producer(api, mail)
    bia = producer(api, mail, "bia@example.org")
    original = animal(api, ana)
    other = animal(api, bia)
    before = one("SELECT id,farm_id,brinco,name FROM animals ORDER BY id")

    async def scenario():
        engine = create_async_engine(database_url(), poolclass=NullPool)
        try:
            factory = async_sessionmaker(engine, expire_on_commit=False)
            async with factory() as source:
                snapshot, media = await farm_snapshot(
                    source, UUID(ana["farm"]["id"]), TEST_STORAGE
                )
            async with factory() as target:
                report = await recover_farm(target, snapshot, media, TEST_STORAGE)
                assert report["applied"] is False
                assert report["tables"]["animals"] == 1
            async with factory() as target:
                return await recover_farm(
                    target, snapshot, media, TEST_STORAGE, apply=True
                )
        finally:
            await engine.dispose()

    recovered = asyncio.run(scenario())
    assert recovered["applied"] is True and recovered["farm_id"] != ana["farm"]["id"]
    assert (
        one(
            "SELECT id,farm_id,brinco,name FROM animals WHERE farm_id<>:f ORDER BY id",
            f=recovered["farm_id"],
        )
        == before
    )
    assert (
        one("SELECT count(*) FROM animals WHERE farm_id=:f", f=recovered["farm_id"])[0][
            0
        ]
        == 1
    )
    assert (
        api.get(f"/api/animals/{other['id']}", headers=headers(bia)).status_code == 200
    )
