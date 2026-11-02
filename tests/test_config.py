from case_lab.config import DEFAULT_PROXY_BASE_URL, get_settings, load_dotenv


def test_default_llm_endpoint_is_proxyapi(monkeypatch):
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("CASE_LLM", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    settings = get_settings(reload_env=False)
    assert settings.base_url == DEFAULT_PROXY_BASE_URL
    assert settings.case_llm == "replay"
    assert settings.model == "gpt-4o-mini"


def test_dotenv_does_not_override_existing_env(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "CASE_LLM=live\nOPENAI_BASE_URL=https://api.proxyapi.ru/v1\nOPENAI_API_KEY=from-file\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENAI_API_KEY", "from-shell")
    monkeypatch.delenv("CASE_LLM", raising=False)
    load_dotenv(env_file)
    assert get_settings(reload_env=False).api_key == "from-shell"

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("CASE_LLM", raising=False)
    load_dotenv(env_file)
    settings = get_settings(reload_env=False)
    assert settings.case_llm == "live"
    assert settings.api_key == "from-file"
