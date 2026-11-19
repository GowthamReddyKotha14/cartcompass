import pytest

from cartcompass.kroger import KrogerClient, KrogerError, load_credentials
from fake_kroger import FakeKroger, product


def client(fake):
    return KrogerClient("id", "secret", transport=fake, sleep=lambda s: None)


def test_stores_near_zip():
    stores = client(FakeKroger()).stores("43402", radius_miles=15)
    assert [s.city for s in stores] == ["Bowling Green", "Waterville"]
    assert stores[0].location_id == "01600878" and stores[0].lat


def test_token_is_fetched_once_and_reused():
    fake = FakeKroger()
    c = client(fake)
    c.stores("43402"); c.products("milk", "01600878")
    assert sum(url.endswith("/token") for _, url in fake.requests) == 1


def test_retries_rate_limits_and_server_errors():
    fake = FakeKroger(fail=[429, 503])
    assert len(client(fake).stores("43402")) == 2


def test_gives_up_with_a_clear_error():
    with pytest.raises(KrogerError, match="HTTP 403"):
        client(FakeKroger(fail=[403])).stores("43402")


def test_products_pages_past_fifty():
    many = {"S": [product(str(i), f"Milk {i}", "1 gal", 3.0) for i in range(120)]}
    fake = FakeKroger(catalog=many)
    got = client(fake).products("milk", "S", limit=120)
    assert len(got) == 120 and len({p["productId"] for p in got}) == 120
    assert sum("/products" in url for _, url in fake.requests) == 3


def test_credentials_from_file(tmp_path, monkeypatch):
    monkeypatch.delenv("KROGER_CLIENT_ID", raising=False)
    monkeypatch.delenv("KROGER_CLIENT_SECRET", raising=False)
    f = tmp_path / "keys.env"
    f.write_text("# keys\nKROGER_CLIENT_ID=abc\nKROGER_CLIENT_SECRET = s3cret\n")
    assert load_credentials(f) == ("abc", "s3cret")
    with pytest.raises(KrogerError):
        load_credentials(tmp_path / "missing.env")


def test_secret_never_appears_in_repr():
    assert "hunter2" not in repr(KrogerClient("id", "hunter2"))
