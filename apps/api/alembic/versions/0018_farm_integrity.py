"""Impedir relações entre dados de fazendas diferentes, inclusive por SQL."""

from alembic import op

revision = "0018_farm_integrity"
down_revision = "0017_producers_and_farms"
branch_labels = depends_on = None

CHECKS = {
    "media_assets": [("imports", "import_id", "farm_id")],
    "event_proposal_sources": [("media_assets", "media_asset_id", "farm_id")],
    "event_proposals": [
        ("event_proposal_sources", "source_id", "farm_id"),
        ("animals", "candidate_animal_id", "farm_id"),
        ("animals", "applied_animal_id", "farm_id"),
    ],
    "animals": [("animals", "merged_into_id", "farm_id")],
    "official_measurements": [
        ("baseline_imports", "baseline_import_id", "farm_id"),
        ("production_imports", "production_import_id", "farm_id"),
        ("event_proposals", "event_proposal_id", "farm_id"),
    ],
}


def upgrade():
    op.execute("""CREATE FUNCTION forbid_farm_reassignment() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN IF NEW.farm_id IS DISTINCT FROM OLD.farm_id THEN RAISE EXCEPTION 'a fazenda de um registro é imutável'; END IF; RETURN NEW; END $$""")
    for parent in ("imports", "baseline_imports", "production_imports", "supplies"):
        op.execute(
            f"CREATE TRIGGER {parent}_preserve_farm BEFORE UPDATE ON {parent} FOR EACH ROW EXECUTE FUNCTION forbid_farm_reassignment()"
        )
    op.execute("""CREATE FUNCTION preserve_farm_producer() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN IF OLD.producer_account_id IS NOT NULL AND NEW.producer_account_id IS DISTINCT FROM OLD.producer_account_id THEN RAISE EXCEPTION 'a conta produtora de uma fazenda é imutável'; END IF; RETURN NEW; END $$""")
    op.execute(
        "CREATE TRIGGER farms_preserve_producer BEFORE UPDATE ON farms FOR EACH ROW EXECUTE FUNCTION preserve_farm_producer()"
    )
    # Cada função usa nomes estáticos da migração, nunca texto do chamador.
    for table, links in CHECKS.items():
        own_farm = (
            "SELECT farm_id INTO own_farm FROM animals WHERE id=NEW.animal_id;"
            if table == "official_measurements"
            else "own_farm := NEW.farm_id;"
        )
        checks = []
        for parent, column, farm_column in links:
            checks.append(f"""IF NEW.{column} IS NOT NULL THEN
              SELECT {farm_column} INTO parent_farm FROM {parent} WHERE id=NEW.{column};
              IF parent_farm IS DISTINCT FROM own_farm THEN RAISE EXCEPTION 'referência entre fazendas diferentes: {table}.{column}'; END IF;
            END IF;""")
        if table == "official_measurements":
            checks.append("""IF NEW.supersedes_measurement_id IS NOT NULL THEN
              SELECT a.farm_id INTO parent_farm FROM official_measurements m JOIN animals a ON a.id=m.animal_id WHERE m.id=NEW.supersedes_measurement_id;
              IF parent_farm IS DISTINCT FROM own_farm THEN RAISE EXCEPTION 'correção entre fazendas diferentes'; END IF;
            END IF;""")
        if table == "official_measurements":
            checks.append("""IF TG_OP='UPDATE' THEN
              SELECT farm_id INTO parent_farm FROM animals WHERE id=OLD.animal_id;
              IF parent_farm IS DISTINCT FROM own_farm THEN RAISE EXCEPTION 'medição não pode mudar de fazenda'; END IF;
            END IF;
            IF NEW.extracted_line_id IS NOT NULL THEN
              SELECT m.farm_id INTO parent_farm FROM extracted_lines l JOIN extraction_runs r ON r.id=l.extraction_run_id JOIN media_assets m ON m.id=r.media_asset_id WHERE l.id=NEW.extracted_line_id;
              IF parent_farm IS DISTINCT FROM own_farm THEN RAISE EXCEPTION 'leitura de origem em outra fazenda'; END IF;
            END IF;
            IF NEW.review_decision_id IS NOT NULL THEN
              SELECT m.farm_id INTO parent_farm FROM review_decisions d JOIN extracted_lines l ON l.id=d.extracted_line_id JOIN extraction_runs r ON r.id=l.extraction_run_id JOIN media_assets m ON m.id=r.media_asset_id WHERE d.id=NEW.review_decision_id;
              IF parent_farm IS DISTINCT FROM own_farm THEN RAISE EXCEPTION 'revisão de origem em outra fazenda'; END IF;
            END IF;""")
        immutable = (
            ""
            if table == "official_measurements"
            else "IF TG_OP='UPDATE' AND NEW.farm_id IS DISTINCT FROM OLD.farm_id THEN RAISE EXCEPTION 'a fazenda de um registro é imutável'; END IF;"
        )
        op.execute(f"""CREATE FUNCTION check_{table}_farm_links() RETURNS trigger LANGUAGE plpgsql AS $$
          DECLARE own_farm uuid; parent_farm uuid;
          BEGIN {immutable} {own_farm} {" ".join(checks)} RETURN NEW; END $$;""")
        op.execute(
            f"CREATE TRIGGER {table}_farm_links BEFORE INSERT OR UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION check_{table}_farm_links();"
        )


def downgrade():
    for table in reversed(CHECKS):
        op.execute(f"DROP TRIGGER {table}_farm_links ON {table}")
        op.execute(f"DROP FUNCTION check_{table}_farm_links()")
    op.execute("DROP TRIGGER IF EXISTS farms_preserve_producer ON farms")
    op.execute("DROP FUNCTION IF EXISTS preserve_farm_producer()")
    for parent in ("imports", "baseline_imports", "production_imports", "supplies"):
        op.execute(f"DROP TRIGGER IF EXISTS {parent}_preserve_farm ON {parent}")
    op.execute("DROP FUNCTION IF EXISTS forbid_farm_reassignment()")
