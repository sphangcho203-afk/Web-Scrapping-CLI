from fastapi.testclient import TestClient

from app import app


def test_web_ui_serves_index_html():
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert "INTERNET HANDS" in response.text
    assert "Scraper & Extractor Studio" in response.text


def test_web_ui_serves_styles_and_scripts():
    client = TestClient(app)
    css_res = client.get("/styles.css")
    assert css_res.status_code == 200
    assert "--bg-app" in css_res.text

    js_res = client.get("/app.js")
    assert js_res.status_code == 200
    assert "apiCall" in js_res.text
