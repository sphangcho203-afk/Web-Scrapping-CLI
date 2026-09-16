from fastapi.testclient import TestClient

from internet_hands.saas_app import app


def test_web_ui_serves_index_html():
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert "Internet Hands" in response.text
    assert "Web Scraping Studio" in response.text


def test_web_ui_serves_styles_and_scripts():
    client = TestClient(app)
    css_res = client.get("/assets/app.css")
    assert css_res.status_code == 200
    assert "--bg-base" in css_res.text

    js_res = client.get("/assets/app.js")
    assert js_res.status_code == 200
    assert "Internet Hands" in js_res.text
