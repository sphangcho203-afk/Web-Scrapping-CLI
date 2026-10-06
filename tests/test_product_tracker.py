"""Published prices and real transactional product tracking / credit accounting."""
import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from test_content_monitors import content_monitor, due  # noqa: F401 -- reusable isolated DB fixture

from internet_hands.content_monitors import product_arguments, queue_due_content_checks
from internet_hands.control_store import ControlError
from internet_hands.crawl_run_worker import dispatch_run
from internet_hands.crawl_runs import RunStore
from internet_hands.datasets import DatasetStore
from internet_hands.monitor_lifecycle import validate_monitor_spec
from internet_hands.product_data import extract_products, product_fingerprint


def html(price="99.00", availability="InStock", extra="", name="Example product"):
    product = {"@context": "https://schema.org", "@type": "Product", "name": name,
               "sku": "example-1", "offers": {"@type": "Offer", "price": price,
               "priceCurrency": "INR", "availability": "https://schema.org/" + availability}}
    return '<script type="application/ld+json">' + json.dumps(product) + '</script><p>' + extra + '</p>'


def test_product_prices_preserve_exact_source_values_and_ignore_page_text():
    rows, error = extract_products(html(), "https://example.com/product")
    assert not error
    assert rows[0]["price"] == "99" and rows[0]["currency"] == "INR"
    assert rows[0]["extraction_source"] == "published_json_ld"
    changed, _ = extract_products(html("99", extra="Unrelated banner changed"), "https://example.com/product")
    assert product_fingerprint(rows, ["price", "availability"]) == product_fingerprint(changed, ["price", "availability"])
    changed, _ = extract_products(html("79"), "https://example.com/product")
    assert rows[0]["product_id"] == changed[0]["product_id"]
    assert product_fingerprint(rows, ["price"]) != product_fingerprint(changed, ["price"])


@pytest.mark.parametrize("price", [True, None, "₹99", "1,299", "-1", "NaN", "1e4", "9" * 50])
def test_missing_or_ambiguous_prices_are_never_guessed(price):
    rows, error = extract_products(html(price), "https://example.com/product")
    assert not rows and error == "product_price_unavailable"


def test_jsonld_graph_offer_references_and_array_products():
    graph = {"@graph": [{"@type": "Product", "name": "Graph product", "offers": {"@id": "#offer"}},
                         {"@id": "#offer", "@type": "Offer", "price": "0", "priceCurrency": "USD"}]}
    rows, error = extract_products('<script type="application/ld+json">' + json.dumps(graph) + '</script>', "https://example.com/p")
    assert not error and rows[0]["price"] == "0"


def test_aggregate_conflicting_and_oversized_metadata_fail_closed():
    body = html().replace('"Offer"', '"AggregateOffer"')
    assert extract_products(body, "https://example.com/p")[1] == "product_price_unavailable"
    assert extract_products(html() + html("79"), "https://example.com/p")[1] == "ambiguous_product_offers"
    assert extract_products('<script type="application/ld+json">' + 'x' * 128_001 + '</script>', "https://example.com/p")[1] == "product_data_limit"
    assert extract_products('<script type="application/ld+json">[</script>', "https://example.com/p")[1] == "invalid_product_data"


def test_product_monitor_requires_explicit_fields_and_credit_ceiling():
    spec = {"name": "Product", "type": "product", "target": "https://example.com/p",
            "config": {"api_key_id": "key_test", "fields": ["price"], "max_charge_credits": 10}}
    assert validate_monitor_spec(spec)["type"] == "product"
    for fields in ([], ["text"], [1]):
        with pytest.raises(ValueError, match="select"):
            validate_monitor_spec({**spec, "config": {**spec["config"], "fields": fields}})
    for limit in (True, -1, 1.5, "10"):
        with pytest.raises(ValueError, match="whole"):
            validate_monitor_spec({**spec, "config": {**spec["config"], "max_charge_credits": limit}})


@pytest.fixture
def product_monitor(request):
    fixture = request.getfixturevalue("content_monitor")
    control, owner, monitor, key, capture = fixture
    config = {"api_key_id": key["id"], "fields": ["price", "availability"], "max_charge_credits": 10000}
    with control._connect() as conn, conn.cursor() as cur:
        cur.execute("UPDATE ih_monitors SET type='product',config=%s::jsonb WHERE id=%s", (json.dumps(config), monitor["id"]))
    capture["text"] = html()
    return control, owner, monitor, key, capture


async def scheduled_check(control, monitor):
    due(control, monitor)
    assert queue_due_content_checks(control)["queued"] == 1
    assert (await dispatch_run(RunStore(control)))["processed"] == 1


async def test_product_tracking_baseline_changes_unchanged_missing_and_charge_release(product_monitor):
    control, owner, monitor, _key, capture = product_monitor
    await scheduled_check(control, monitor)
    first = control.get_monitor(owner, monitor["id"])
    assert first["last_status"] == "baseline"
    dataset = DatasetStore(control).get(owner, first["baseline_dataset_id"])
    assert dataset["operation"] == "product" and dataset["rows"][0]["price"] == "99"
    capture["text"] = html(extra="Banner is different")
    await scheduled_check(control, monitor)
    unchanged = control.get_monitor(owner, monitor["id"])
    assert unchanged["last_status"] == "unchanged" and unchanged["baseline_dataset_id"] == dataset["id"]
    capture["text"] = html("79", "OutOfStock")
    await scheduled_check(control, monitor)
    changed = control.get_monitor(owner, monitor["id"])
    assert changed["last_status"] == "changed" and changed["baseline_dataset_id"] != dataset["id"]
    changes = changed["runs"][0]["diff"]["changes"]
    assert changes[0]["before"]["price"] == "99" and changes[0]["after"]["price"] == "79"
    capture["text"] = "No published product metadata"
    await scheduled_check(control, monitor)
    failed = control.get_monitor(owner, monitor["id"])
    assert failed["last_status"] == "failed" and failed["baseline_hash"] == changed["baseline_hash"]
    assert failed["runs"][0]["credits_charged"] == 0
    with control._connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT purchased_credits,monthly_credits,reserved_credits FROM ih_wallets WHERE user_id=%s", (owner,))
        wallet = cur.fetchone()
        assert wallet["reserved_credits"] == 0
        assert 10000 - wallet["monthly_credits"] == sum(run["credits_charged"] for run in failed["runs"])
        cur.execute("SELECT count(*) AS n FROM ih_datasets WHERE user_id=%s", (owner,))
        assert cur.fetchone()["n"] == 2


async def test_preview_seed_is_atomic_idempotent_and_does_not_charge_again(product_monitor, monkeypatch):
    from internet_hands import product_tracker_api
    control, owner, monitor, key, _capture = product_monitor
    monkeypatch.setattr(product_tracker_api, "store", control)
    # Remove fixture monitor to keep free-plan capacity available.
    with control._connect() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM ih_monitors WHERE id=%s", (monitor["id"],))
    runs = RunStore(control)
    identity = control.api_key_identity_for_user(owner, key["id"])
    run = runs.create(identity, "product-preview", product_arguments("https://example.com/pricing"))
    await dispatch_run(runs, run["id"])
    preview = product_tracker_api.product_run(owner, run["id"])
    assert preview["run"]["status"] == "completed" and preview["products"][0]["price"] == "99"
    assert runs.create(identity, "product-preview", product_arguments("https://example.com/pricing"))["id"] == run["id"]
    body = {"run_id": run["id"], "name": "My product", "confirm_recurring": True}
    before = control.account_snapshot(owner)["monthly_credits"]
    with ThreadPoolExecutor(2) as pool:
        created = list(pool.map(lambda _: product_tracker_api.start_tracking(owner, body), range(2)))
    assert created[0]["id"] == created[1]["id"]
    assert created[0]["baseline_dataset_id"] == preview["run"]["dataset_id"]
    assert control.account_snapshot(owner)["monthly_credits"] == before
    with pytest.raises(ControlError, match="already"):
        product_tracker_api.start_tracking(owner, {**body, "name": "Another name"})
    with pytest.raises(ControlError) as error:
        product_tracker_api.product_run("foreign", run["id"])
    assert error.value.status_code == 404


async def test_missing_preview_is_uncharged_and_cannot_enable_tracking(product_monitor, monkeypatch):
    from fastapi import HTTPException

    from internet_hands import product_tracker_api
    control, owner, monitor, key, capture = product_monitor
    monkeypatch.setattr(product_tracker_api, "store", control)
    capture["text"] = "A number 99 is not a published offer"
    run = RunStore(control).create(control.api_key_identity_for_user(owner, key["id"]), "missing-price", product_arguments(monitor["target"]))
    await dispatch_run(RunStore(control), run["id"])
    finished = RunStore(control).get(owner, run["id"])
    assert finished["status"] == "failed" and finished["credits_charged"] == 0 and not finished["dataset_id"]
    with pytest.raises(ControlError, match="successful"):
        product_tracker_api.start_tracking(owner, {"run_id": run["id"], "name": "Invalid", "confirm_recurring": True})
    with pytest.raises(HTTPException, match="recurring"):
        product_tracker_api.start_tracking(owner, {"run_id": run["id"], "name": "Invalid"})


async def test_product_cap_and_paused_job_prevent_work(product_monitor):
    control, owner, monitor, _key, _capture = product_monitor
    with control._connect() as conn, conn.cursor() as cur:
        cur.execute("UPDATE ih_monitors SET config=jsonb_set(config,'{max_charge_credits}','0') WHERE id=%s", (monitor["id"],))
    due(control, monitor)
    assert queue_due_content_checks(control)["blocked"] == 1
    assert control.get_monitor(owner, monitor["id"])["runs"][0]["credits_charged"] == 0
    with control._connect() as conn, conn.cursor() as cur:
        cur.execute("UPDATE ih_monitors SET config=jsonb_set(config,'{max_charge_credits}','10000') WHERE id=%s", (monitor["id"],))
    due(control, monitor)
    assert queue_due_content_checks(control)["queued"] == 1
    control.toggle_monitor(owner, monitor["id"], False)
    await dispatch_run(RunStore(control))
    assert control.get_monitor(owner, monitor["id"])["runs"][0]["credits_charged"] == 0
