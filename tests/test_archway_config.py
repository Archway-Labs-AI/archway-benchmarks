from archway_benchmarks.archway_config import (
    DEFAULT_SERVER_URL,
    ENV_SERVER_URL,
    resolve_archway_server_config,
)


def test_archway_server_url_defaults_to_localhost(tmp_path, monkeypatch):
    monkeypatch.delenv(ENV_SERVER_URL, raising=False)

    cfg = resolve_archway_server_config(start_dir=tmp_path)

    assert cfg.server_url == DEFAULT_SERVER_URL
    assert cfg.source == "default"


def test_archway_server_url_reads_archway_toml(tmp_path, monkeypatch):
    monkeypatch.delenv(ENV_SERVER_URL, raising=False)
    (tmp_path / "archway.toml").write_text(
        '[archway]\nserver_url = "http://tailscale-host:8788/"\n'
    )
    nested = tmp_path / "nested"
    nested.mkdir()

    cfg = resolve_archway_server_config(start_dir=nested)

    assert cfg.server_url == "http://tailscale-host:8788"
    assert cfg.source == "config"
    assert cfg.config_path == str(tmp_path / "archway.toml")


def test_archway_server_url_env_overrides_config(tmp_path, monkeypatch):
    (tmp_path / "archway.toml").write_text(
        '[archway]\nserver_url = "http://config-host:8788"\n'
    )
    monkeypatch.setenv(ENV_SERVER_URL, "http://env-host:8788/")

    cfg = resolve_archway_server_config(start_dir=tmp_path)

    assert cfg.server_url == "http://env-host:8788"
    assert cfg.source == f"env:{ENV_SERVER_URL}"
    assert cfg.config_path is None


def test_archway_server_url_cli_overrides_env(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_SERVER_URL, "http://env-host:8788")

    cfg = resolve_archway_server_config(
        cli_server_url="http://cli-host:8788/",
        start_dir=tmp_path,
    )

    assert cfg.server_url == "http://cli-host:8788"
    assert cfg.source == "cli"


def test_archway_config_path_is_explicit(tmp_path, monkeypatch):
    monkeypatch.delenv(ENV_SERVER_URL, raising=False)
    path = tmp_path / "custom.toml"
    path.write_text('server_url = "http://configured:8788"\n')

    cfg = resolve_archway_server_config(config_path=path)

    assert cfg.server_url == "http://configured:8788"
