"""systemd 三服务部署工具的静态测试。"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "aiSelfTest"

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def test_project_scripts_only_include_systemd_command() -> None:
    """wheel 安装后只暴露 systemd 部署工具命令。"""

    pyproject = tomllib.loads((BACKEND_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["project"]["scripts"] == {"aiSelfTestSystemd": "aiSelfTest.systemd:main"}


def test_default_config_uses_current_working_directory(monkeypatch, tmp_path) -> None:
    """默认部署目录应使用执行 aiSelfTestSystemd 时的当前目录。"""

    from aiSelfTest.systemd import build_default_config

    monkeypatch.chdir(tmp_path)

    config = build_default_config()

    assert config.deploy_dir == tmp_path
    assert config.env_file == tmp_path / "aiSelfTest.env"
    assert config.bin_dir == Path(sys.executable).resolve().parent


def test_env_file_defaults_to_deploy_dir(tmp_path) -> None:
    """未显式传入 env_file 时，应固定使用 deploy_dir 下的 aiSelfTest.env。"""

    from aiSelfTest.systemd import SystemdConfig

    config = SystemdConfig(deploy_dir=tmp_path)

    assert config.env_file == tmp_path / "aiSelfTest.env"


def test_systemd_renderer_returns_three_services_with_shared_env_file(tmp_path) -> None:
    """systemd 工具应渲染 API、Worker 和 Beat 三个独立服务。"""

    from aiSelfTest.systemd import SystemdConfig, render_service_units

    config = SystemdConfig(deploy_dir=tmp_path, env_file=tmp_path / "aiSelfTest.env")
    units = render_service_units(config)

    assert sorted(units) == [
        "aiSelfTest-api.service",
        "aiSelfTest-beat.service",
        "aiSelfTest-worker.service",
    ]
    assert "python -m aiSelfTest.server" in units["aiSelfTest-api.service"]
    assert "python -m aiSelfTest.worker_server worker" in units["aiSelfTest-worker.service"]
    assert "python -m aiSelfTest.worker_server beat" in units["aiSelfTest-beat.service"]

    for content in units.values():
        assert f"EnvironmentFile={tmp_path / 'aiSelfTest.env'}" in content
        assert f"WorkingDirectory={tmp_path}" in content
        assert "Restart=always" in content


def test_env_template_contains_all_runtime_config_keys(tmp_path) -> None:
    """aiSelfTest.env 模板应覆盖 config.py 中读取的所有运行时配置。"""

    from aiSelfTest.systemd import SystemdConfig, render_env_file

    config = SystemdConfig(deploy_dir=tmp_path, env_file=tmp_path / "aiSelfTest.env")
    env_template = render_env_file(config)
    expected_keys = {
        "DATABASE_URL",
        "REDIS_URL",
        "AI_SELF_TEST_API_HOST",
        "AI_SELF_TEST_API_PORT",
        "AI_SELF_TEST_API_WORKERS",
        "AI_SELF_TEST_DATA_DIR",
        "AI_SELF_TEST_TRAINING_SAVE_DIR",
        "AI_SELF_TEST_CORS_ORIGINS",
        "MODEL_CHAT_TIMEOUT_SECONDS",
        "TASK_WORKER_CONCURRENCY",
        "TASK_TIME_LIMIT_SECONDS",
        "TASK_SOFT_TIME_LIMIT_SECONDS",
        "TASK_BEAT_SCAN_SECONDS",
        "TASK_RUNNING_STALE_SECONDS",
        "TASK_QUEUE_STALE_SECONDS",
        "VIDEO_RECOGNITION_MODE",
        "VIDEO_MAX_FULL_FRAMES_PER_VIDEO",
    }

    for key in expected_keys:
        assert f"{key}=" in env_template


def test_cli_parser_supports_required_subcommands() -> None:
    """命令行工具只提供安装、卸载、启动、停止和重启子命令。"""

    from aiSelfTest.systemd import build_parser

    parser = build_parser()
    subcommands_action = next(action for action in parser._actions if action.dest == "command")

    assert set(subcommands_action.choices) == {
        "install",
        "uninstall",
        "start",
        "stop",
        "restart",
    }


def test_install_services_enables_services(monkeypatch, tmp_path) -> None:
    """install 写入服务后应刷新 systemd 并直接开启开机自启。"""

    from aiSelfTest import systemd

    commands: list[list[str]] = []

    def fake_run_command(command, *, check=True):
        commands.append(list(command))

    monkeypatch.setattr(systemd, "_run_command", fake_run_command)

    config = systemd.SystemdConfig(
        deploy_dir=tmp_path,
        env_file=tmp_path / "aiSelfTest.env",
        service_dir=tmp_path / "systemd",
    )
    systemd.install_services(config)

    assert commands == [
        ["systemctl", "daemon-reload"],
        ["systemctl", "enable", *systemd.SERVICE_NAMES],
    ]
    for service_name in systemd.SERVICE_NAMES:
        assert (config.service_dir / service_name).is_file()


def test_start_stop_restart_use_ordered_systemctl_commands(monkeypatch) -> None:
    """start/stop/restart 应按明确顺序逐个管理三个服务。"""

    from aiSelfTest import systemd

    assert systemd.START_SERVICE_ROLES == ("api", "worker", "beat")
    assert systemd.STOP_SERVICE_ROLES == ("beat", "worker", "api")

    commands: list[list[str]] = []

    def fake_run_command(command, *, check=True):
        commands.append(list(command))

    monkeypatch.setattr(systemd, "_run_command", fake_run_command)

    systemd.start_services()
    systemd.stop_services()
    systemd.restart_services()

    assert commands == [
        ["systemctl", "start", "aiSelfTest-api.service"],
        ["systemctl", "start", "aiSelfTest-worker.service"],
        ["systemctl", "start", "aiSelfTest-beat.service"],
        ["systemctl", "stop", "aiSelfTest-beat.service"],
        ["systemctl", "stop", "aiSelfTest-worker.service"],
        ["systemctl", "stop", "aiSelfTest-api.service"],
        ["systemctl", "stop", "aiSelfTest-beat.service"],
        ["systemctl", "stop", "aiSelfTest-worker.service"],
        ["systemctl", "stop", "aiSelfTest-api.service"],
        ["systemctl", "start", "aiSelfTest-api.service"],
        ["systemctl", "start", "aiSelfTest-worker.service"],
        ["systemctl", "start", "aiSelfTest-beat.service"],
    ]


def test_api_server_runs_migrations_before_uvicorn(monkeypatch) -> None:
    """专用 API 启动入口应先迁移数据库，再启动 uvicorn workers。"""

    from aiSelfTest import server

    calls: list[tuple[str, object]] = []

    monkeypatch.setattr(
        server,
        "configure_deploy_logging",
        lambda service_name: calls.append(("log", service_name)),
    )
    monkeypatch.setattr(server, "run_migrations", lambda: calls.append(("migrate", None)))
    monkeypatch.setenv("AI_SELF_TEST_API_HOST", "127.0.0.1")
    monkeypatch.setenv("AI_SELF_TEST_API_PORT", "3100")
    monkeypatch.setenv("AI_SELF_TEST_API_WORKERS", "3")

    def fake_uvicorn_run(app_path, *, host, port, workers, reload, log_config):
        calls.append(
            (
                "uvicorn",
                {
                    "app_path": app_path,
                    "host": host,
                    "port": port,
                    "workers": workers,
                    "reload": reload,
                    "log_config": log_config,
                },
            )
        )

    monkeypatch.setattr(server.uvicorn, "run", fake_uvicorn_run)

    server.main()

    assert calls == [
        ("log", "api"),
        ("migrate", None),
        (
            "uvicorn",
            {
                "app_path": "aiSelfTest.main:app",
                "host": "127.0.0.1",
                "port": 3100,
                "workers": 3,
                "reload": False,
                "log_config": None,
            },
        ),
    ]


def test_deploy_file_logging_uses_service_specific_file_without_custom_format(
    monkeypatch,
    tmp_path,
) -> None:
    """部署日志配置应移除默认输出，并为每个服务写独立文件。"""

    from aiSelfTest import logging as app_logging

    calls: list[tuple[str, object]] = []

    monkeypatch.setattr(
        app_logging,
        "get_settings",
        lambda: SimpleNamespace(log_dir=tmp_path / "logs"),
    )
    monkeypatch.setattr(app_logging.logger, "remove", lambda: calls.append(("remove", None)))

    def fake_add(*args, **kwargs):
        calls.append(("add", {"args": args, "kwargs": kwargs}))
        return 1

    monkeypatch.setattr(app_logging.logger, "add", fake_add)

    for service_name in ("api", "worker", "beat"):
        app_logging.configure_deploy_file_logging(service_name)

    assert calls[0] == ("remove", None)
    add_calls = [call for call in calls if call[0] == "add"]
    assert [call[1]["args"][0] for call in add_calls] == [
        tmp_path / "logs" / "api.log",
        tmp_path / "logs" / "worker.log",
        tmp_path / "logs" / "beat.log",
    ]
    for _, payload in add_calls:
        kwargs = payload["kwargs"]
        assert kwargs["enqueue"] is True
        assert kwargs["encoding"] == "utf-8"
        assert "format" not in kwargs


def test_worker_server_configures_logging_before_start(monkeypatch) -> None:
    """Worker/Beat 部署入口应先配置文件日志，再启动对应 Celery 进程。"""

    from aiSelfTest import worker_server

    calls: list[tuple[str, str]] = []

    monkeypatch.setattr(
        worker_server,
        "configure_deploy_logging",
        lambda service_name: calls.append(("log", service_name)),
    )
    monkeypatch.setattr(
        worker_server,
        "start_worker_without_logging_config",
        lambda: calls.append(("start", "worker")),
    )
    monkeypatch.setattr(
        worker_server,
        "start_beat_without_logging_config",
        lambda: calls.append(("start", "beat")),
    )

    assert worker_server.main(["worker"]) == 0
    assert worker_server.main(["beat"]) == 0
    assert calls == [
        ("log", "worker"),
        ("start", "worker"),
        ("log", "beat"),
        ("start", "beat"),
    ]


def test_development_entrypoints_do_not_configure_deploy_file_logging() -> None:
    """开发启动脚本不应调用部署文件日志配置。"""

    assert "configure_deploy_logging" not in (BACKEND_ROOT / "run.py").read_text(encoding="utf-8")
    assert "configure_deploy_logging" not in (BACKEND_ROOT / "run_worker.py").read_text(encoding="utf-8")
    assert "configure_deploy_logging" not in (BACKEND_ROOT / "run_beat.py").read_text(encoding="utf-8")


def test_run_py_uses_api_server_without_deploy_logging() -> None:
    """开发 API 启动脚本应复用最新 API 启动流程但关闭部署文件日志。"""

    source = (BACKEND_ROOT / "run.py").read_text(encoding="utf-8")

    assert "from aiSelfTest.server import main" in source
    assert "main(configure_file_logging=False)" in source


@pytest.mark.parametrize(
    "command,expected_commands",
    [
        (
            "install",
            [
                ["systemctl", "daemon-reload"],
                [
                    "systemctl",
                    "enable",
                    "aiSelfTest-api.service",
                    "aiSelfTest-worker.service",
                    "aiSelfTest-beat.service",
                ],
            ],
        ),
        (
            "uninstall",
            [
                ["systemctl", "stop", "aiSelfTest-beat.service"],
                ["systemctl", "stop", "aiSelfTest-worker.service"],
                ["systemctl", "stop", "aiSelfTest-api.service"],
                [
                    "systemctl",
                    "disable",
                    "aiSelfTest-api.service",
                    "aiSelfTest-worker.service",
                    "aiSelfTest-beat.service",
                ],
                ["systemctl", "daemon-reload"],
            ],
        ),
        (
            "start",
            [
                ["systemctl", "start", "aiSelfTest-api.service"],
                ["systemctl", "start", "aiSelfTest-worker.service"],
                ["systemctl", "start", "aiSelfTest-beat.service"],
            ],
        ),
        (
            "stop",
            [
                ["systemctl", "stop", "aiSelfTest-beat.service"],
                ["systemctl", "stop", "aiSelfTest-worker.service"],
                ["systemctl", "stop", "aiSelfTest-api.service"],
            ],
        ),
        (
            "restart",
            [
                ["systemctl", "stop", "aiSelfTest-beat.service"],
                ["systemctl", "stop", "aiSelfTest-worker.service"],
                ["systemctl", "stop", "aiSelfTest-api.service"],
                ["systemctl", "start", "aiSelfTest-api.service"],
                ["systemctl", "start", "aiSelfTest-worker.service"],
                ["systemctl", "start", "aiSelfTest-beat.service"],
            ],
        ),
    ],
)
def test_systemd_commands_do_not_require_runtime_config(
    command: str,
    expected_commands: list[list[str]],
    monkeypatch,
    tmp_path,
) -> None:
    """systemd 管理命令不应要求数据库、Redis 等运行时配置。"""

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)

    from aiSelfTest import systemd

    commands: list[list[str]] = []
    monkeypatch.setattr(
        systemd,
        "_run_command",
        lambda command, *, check=True: commands.append(list(command)),
    )

    result = systemd.main(
        [
            "--deploy-dir",
            str(tmp_path),
            "--service-dir",
            str(tmp_path / "systemd"),
            command,
        ]
    )

    assert result == 0
    if command == "install":
        assert (tmp_path / "aiSelfTest.env").is_file()
    assert commands == expected_commands
