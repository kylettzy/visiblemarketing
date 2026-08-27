import app as application


def test_login_page_includes_google_sign_in():
    application.app.config.update(TESTING=True)
    with application.app.test_client() as client:
        response = client.get("/login")

    assert response.status_code == 200
    assert b"Continue with Google" in response.data
    assert b'href="/oauth/google"' in response.data


def test_oauth_callback_uses_configured_cloudflare_hostname(monkeypatch):
    monkeypatch.setattr(
        application, "PUBLIC_BASE_URL", "https://portal.example.com"
    )
    with application.app.test_request_context("/login", base_url="http://localhost"):
        callback = application.oauth_callback_url("google")

    assert callback == "https://portal.example.com/oauth/google/callback"


def test_request_hostname_is_used_without_public_url(monkeypatch):
    monkeypatch.setattr(application, "PUBLIC_BASE_URL", "")
    with application.app.test_request_context(
        "/login", base_url="https://portal.example.com"
    ):
        callback = application.oauth_callback_url("google")

    assert callback == "https://portal.example.com/oauth/google/callback"
