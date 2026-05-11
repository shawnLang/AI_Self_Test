"""systemd 三服务部署辅助工具。"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence


@dataclass(frozen=True)
class ServiceUnit:
    """单个 systemd 服务的角色与文件名。"""

    role: str
    file_name: str


API_SERVICE = ServiceUnit(role="api", file_name="aiSelfTest-api.service")
WORKER_SERVICE = ServiceUnit(role="worker", file_name="aiSelfTest-worker.service")
BEAT_SERVICE = ServiceUnit(role="beat", file_name="aiSelfTest-beat.service")
SERVICE_UNITS = (API_SERVICE, WORKER_SERVICE, BEAT_SERVICE)
SERVICE_NAMES = tuple(service.file_name for service in SERVICE_UNITS)
START_SERVICE_ROLES = ("api", "worker", "beat")
STOP_SERVICE_ROLES = ("beat", "worker", "api")


@dataclass(frozen=True)
class SystemdConfig:
    """systemd 服务渲染配置。"""

    app_name: str = "aiSelfTest"
    deploy_dir: Path = field(default_factory=lambda: Path.cwd().resolve())
    env_file: Path | None = None
    bin_dir: Path = field(default_factory=lambda: Path(sys.executable).resolve().parent)
    service_dir: Path = Path("/etc/systemd/system")
    user: str = "root"
    group: str = "root"
    api_host: str = "0.0.0.0"
    api_port: int = 3001
    api_workers: int = 1
    worker_concurrency: int = 2

    def __post_init__(self) -> None:
        """补全依赖部署目录派生的默认路径。"""

        deploy_dir = self.deploy_dir.resolve()
        env_file = self.env_file.resolve() if self.env_file is not None else deploy_dir / "aiSelfTest.env"
        object.__setattr__(self, "deploy_dir", deploy_dir)
        object.__setattr__(self, "env_file", env_file)


def build_default_config() -> SystemdConfig:
    """基于当前执行目录与 Python 环境创建默认 systemd 配置。"""

    deploy_dir = Path.cwd().resolve()
    return SystemdConfig(
        deploy_dir=deploy_dir,
        bin_dir=Path(sys.executable).resolve().parent,
    )


def render_service_units(config: SystemdConfig) -> dict[str, str]:
    """渲染 API、Celery Worker 与 Celery Beat 三个 systemd 服务。"""

    return {
        "aiSelfTest-api.service": _render_service(
            description="aiSelfTest FastAPI service",
            config=config,
            exec_start=f"{config.bin_dir / 'python'} -m aiSelfTest.server",
        ),
        "aiSelfTest-worker.service": _render_service(
            description="aiSelfTest Celery worker service",
            config=config,
            exec_start=f"{config.bin_dir / 'python'} -m aiSelfTest.worker_server worker",
        ),
        "aiSelfTest-beat.service": _render_service(
            description="aiSelfTest Celery beat service",
            config=config,
            exec_start=f"{config.bin_dir / 'python'} -m aiSelfTest.worker_server beat",
        ),
    }


def render_env_file(config: SystemdConfig) -> str:
    """渲染包含全部运行时配置项的 aiSelfTest.env 模板。"""

    return "\n".join(
        [
            "# aiSelfTest runtime environment",
            "# Replace database, redis and secret values before starting services.",
            "",
            "DATABASE_URL=postgresql://user:password@127.0.0.1:5432/ai_self_test",
            "REDIS_URL=redis://127.0.0.1:6379/0",
            f"AI_SELF_TEST_API_HOST={config.api_host}",
            f"AI_SELF_TEST_API_PORT={config.api_port}",
            f"AI_SELF_TEST_API_WORKERS={config.api_workers}",
            f"AI_SELF_TEST_DATA_DIR={config.deploy_dir / 'data'}",
            f"AI_SELF_TEST_TRAINING_SAVE_DIR={config.deploy_dir / 'data' / 'training'}",
            "AI_SELF_TEST_CORS_ORIGINS=http://localhost:5173,http://localhost:3000",
            "",
            "MODEL_CHAT_TIMEOUT_SECONDS=300",
            f"TASK_WORKER_CONCURRENCY={config.worker_concurrency}",
            "TASK_TIME_LIMIT_SECONDS=21600",
            "TASK_SOFT_TIME_LIMIT_SECONDS=21000",
            "TASK_BEAT_SCAN_SECONDS=60",
            "TASK_RUNNING_STALE_SECONDS=21600",
            "TASK_QUEUE_STALE_SECONDS=600",
            "",
            "VIDEO_RECOGNITION_MODE=full_frame",
            "VIDEO_MAX_FULL_FRAMES_PER_VIDEO=30",
            "",
        ]
    )


def build_parser() -> argparse.ArgumentParser:
    """创建 systemd 部署工具命令行解析器。"""

    default_config = build_default_config()
    parser = argparse.ArgumentParser(description="Manage aiSelfTest systemd services.")
    parser.add_argument("--deploy-dir", type=Path, default=default_config.deploy_dir)
    parser.add_argument("--env-file", type=Path, default=None)
    parser.add_argument("--service-dir", type=Path, default=default_config.service_dir)
    parser.add_argument("--user", default=default_config.user)
    parser.add_argument("--group", default=default_config.group)
    parser.add_argument("--api-host", default=default_config.api_host)
    parser.add_argument("--api-port", type=int, default=default_config.api_port)
    parser.add_argument("--api-workers", type=int, default=default_config.api_workers)
    parser.add_argument("--worker-concurrency", type=int, default=default_config.worker_concurrency)

    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in (
        "install",
        "uninstall",
        "start",
        "stop",
        "restart",
    ):
        subparsers.add_parser(command)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """执行 systemd 三服务管理命令。"""

    parser = build_parser()
    args = parser.parse_args(argv)
    config = _config_from_args(args)

    if args.command == "install":
        install_services(config)
        return 0
    if args.command == "uninstall":
        uninstall_services(config)
        return 0
    if args.command == "start":
        start_services()
        return 0
    if args.command == "stop":
        stop_services()
        return 0
    if args.command == "restart":
        restart_services()
        return 0

    return 0


def install_services(config: SystemdConfig) -> None:
    """写入三个 service 文件并刷新 systemd 配置。"""

    config.service_dir.mkdir(parents=True, exist_ok=True)
    for name, content in render_service_units(config).items():
        (config.service_dir / name).write_text(content, encoding="utf-8")
    if not config.env_file.exists():
        config.env_file.parent.mkdir(parents=True, exist_ok=True)
        config.env_file.write_text(render_env_file(config), encoding="utf-8")
    _run_command(["systemctl", "daemon-reload"])
    run_systemctl_command("enable", SERVICE_NAMES)


def uninstall_services(config: SystemdConfig) -> None:
    """停止、禁用并删除三个 systemd service 文件。"""

    stop_services(check=False)
    run_systemctl_command("disable", SERVICE_NAMES, check=False)
    for service_name in SERVICE_NAMES:
        service_path = config.service_dir / service_name
        if service_path.exists():
            service_path.unlink()
    _run_command(["systemctl", "daemon-reload"])


def start_services(*, check: bool = True) -> None:
    """按 API、Worker、Beat 顺序启动服务。"""

    for service_name in _service_names_by_roles(START_SERVICE_ROLES):
        run_systemctl_command("start", (service_name,), check=check)


def stop_services(*, check: bool = True) -> None:
    """按 Beat、Worker、API 顺序停止服务。"""

    for service_name in _service_names_by_roles(STOP_SERVICE_ROLES):
        run_systemctl_command("stop", (service_name,), check=check)


def restart_services() -> None:
    """先按停止顺序停止，再按启动顺序启动服务。"""

    stop_services()
    start_services()


def run_systemctl_command(command: str, service_names: Sequence[str], *, check: bool = True) -> None:
    """对三个 aiSelfTest 服务执行指定 systemctl 命令。"""

    _run_command(["systemctl", command, *service_names], check=check)


def _render_service(description: str, config: SystemdConfig, exec_start: str) -> str:
    """渲染单个 systemd service 文件内容。"""

    return "\n".join(
        [
            "[Unit]",
            f"Description={description}",
            "After=network-online.target",
            "Wants=network-online.target",
            "",
            "[Service]",
            "Type=simple",
            f"User={config.user}",
            f"Group={config.group}",
            f"WorkingDirectory={config.deploy_dir}",
            f"EnvironmentFile={config.env_file}",
            f"ExecStart={exec_start}",
            "Restart=always",
            "RestartSec=5",
            "KillSignal=SIGTERM",
            "TimeoutStopSec=30",
            "",
            "[Install]",
            "WantedBy=multi-user.target",
            "",
        ]
    )


def _config_from_args(args: argparse.Namespace) -> SystemdConfig:
    """根据命令行参数构建 systemd 配置。"""

    deploy_dir = args.deploy_dir.resolve()
    env_file = args.env_file.resolve() if args.env_file is not None else deploy_dir / "aiSelfTest.env"
    return SystemdConfig(
        deploy_dir=deploy_dir,
        env_file=env_file,
        bin_dir=Path(sys.executable).resolve().parent,
        service_dir=args.service_dir,
        user=args.user,
        group=args.group,
        api_host=args.api_host,
        api_port=args.api_port,
        api_workers=args.api_workers,
        worker_concurrency=args.worker_concurrency,
    )


def _service_names_by_roles(roles: Sequence[str]) -> tuple[str, ...]:
    """根据服务职责返回服务文件名，避免顺序依赖文件名排序。"""

    service_by_role = {service.role: service.file_name for service in SERVICE_UNITS}
    return tuple(service_by_role[role] for role in roles)


def _run_command(command: Sequence[str], *, check: bool = True) -> None:
    """执行外部命令。"""

    subprocess.run(command, check=check)


if __name__ == "__main__":
    raise SystemExit(main())
