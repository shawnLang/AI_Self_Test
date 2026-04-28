"""aiSelfTest 文档与日志补强的轻量静态检查。"""

from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "aiSelfTest"
PACKAGE_ROOT = BACKEND_ROOT / "aiSelfTest"

TOP_LEVEL_PYTHON_FILES = (
    BACKEND_ROOT / "build_utils.py",
    BACKEND_ROOT / "run.py",
    BACKEND_ROOT / "setup.py",
    BACKEND_ROOT / "setup_build.py",
)

BASELINE_LOGURU_HOTSPOTS = (
    PACKAGE_ROOT / "database.py",
    PACKAGE_ROOT / "exceptions.py",
    PACKAGE_ROOT / "main.py",
    PACKAGE_ROOT / "services" / "client_auth.py",
    PACKAGE_ROOT / "services" / "multimodal_chat.py",
    PACKAGE_ROOT / "services" / "multimodal_gateway.py",
    PACKAGE_ROOT / "services" / "task_execution.py",
    PACKAGE_ROOT / "services" / "task_scheduler.py",
)

STRICT_LOGURU_HOTSPOTS = (
    PACKAGE_ROOT / "api" / "client.py",
    PACKAGE_ROOT / "api" / "config.py",
    PACKAGE_ROOT / "api" / "dashboard.py",
    PACKAGE_ROOT / "api" / "multimodal_model.py",
    PACKAGE_ROOT / "api" / "review.py",
    PACKAGE_ROOT / "api" / "task.py",
    PACKAGE_ROOT / "services" / "client.py",
    PACKAGE_ROOT / "services" / "config.py",
    PACKAGE_ROOT / "services" / "multimodal_attachment.py",
    PACKAGE_ROOT / "services" / "multimodal_model_crud.py",
    PACKAGE_ROOT / "services" / "task.py",
)

SENSITIVE_NAME_PARTS = (
    "access_token",
    "api_key",
    "password",
    "refresh_token",
    "secret",
    "token",
)


def test_static_scope_covers_specified_python_files() -> None:
    """确认静态检查覆盖规格要求的后端 Python 文件。"""

    paths = _backend_python_files()

    assert (BACKEND_ROOT / "build_utils.py") in paths
    assert (BACKEND_ROOT / "setup.py") in paths
    assert (BACKEND_ROOT / "setup_build.py") in paths
    assert any(path.name == "task_execution.py" for path in paths)
    assert any(path.name == "task_scheduler.py" for path in paths)

    for path in paths:
        ast.parse(_read_source(path), filename=str(path))


def test_non_empty_modules_have_module_docstrings() -> None:
    """非空后端模块应具备模块级说明，便于维护者快速理解用途。"""

    missing_docstrings: list[str] = []

    for path in _backend_python_files():
        source = _read_source(path)
        if not source.strip():
            continue

        tree = ast.parse(source, filename=str(path))
        if ast.get_docstring(tree) is None:
            missing_docstrings.append(_relative(path))

    assert missing_docstrings == []


def test_loguru_is_the_only_runtime_logging_facade() -> None:
    """后端运行时日志应统一使用 loguru，避免混用 stdlib logging。"""

    violations: list[str] = []

    for path in _backend_python_files():
        tree = ast.parse(_read_source(path), filename=str(path))
        imports_loguru_logger = _imports_loguru_logger(tree)
        imports_stdlib_logging = _imports_stdlib_logging(tree)
        logger_call_count = _logger_call_count(tree)

        if imports_stdlib_logging:
            violations.append(f"{_relative(path)} imports stdlib logging")
        if logger_call_count and not imports_loguru_logger:
            violations.append(f"{_relative(path)} uses logger without loguru import")

    assert violations == []


def test_baseline_observability_hotspots_have_loguru_calls() -> None:
    """已具备日志的关键路径必须保持 loguru 调用，防止后续回退。"""

    missing_logger_calls = [
        _relative(path)
        for path in BASELINE_LOGURU_HOTSPOTS
        if _logger_call_count(ast.parse(_read_source(path), filename=str(path))) == 0
    ]

    assert missing_logger_calls == []


def test_logger_calls_do_not_pass_sensitive_values() -> None:
    """日志调用不得直接传入密码、令牌、密钥等高风险敏感值。"""

    violations: list[str] = []

    for path in _backend_python_files():
        tree = ast.parse(_read_source(path), filename=str(path))
        for node in ast.walk(tree):
            if not _is_logger_call(node):
                continue

            expressions = [*node.args, *(keyword.value for keyword in node.keywords)]
            for expression in expressions:
                if isinstance(expression, ast.Constant):
                    continue
                sensitive_names = _sensitive_names_in_expression(expression)
                if sensitive_names:
                    names = ", ".join(sorted(sensitive_names))
                    violations.append(f"{_relative(path)}:{node.lineno} logs {names}")

    assert violations == []


def test_strict_doc_log_acceptance_when_enabled() -> None:
    """集成实现后可启用严格模式，校验 API 与服务层新增日志覆盖。"""

    if os.environ.get("AI_SELFTEST_STRICT_DOC_LOG_CHECKS") != "1":
        pytest.skip("set AI_SELFTEST_STRICT_DOC_LOG_CHECKS=1 after implementation")

    missing_logger_calls = [
        _relative(path)
        for path in STRICT_LOGURU_HOTSPOTS
        if _logger_call_count(ast.parse(_read_source(path), filename=str(path))) == 0
    ]

    assert missing_logger_calls == []


def _backend_python_files() -> list[Path]:
    """返回规格覆盖的后端 Python 文件列表。"""

    paths = set(PACKAGE_ROOT.rglob("*.py"))
    paths.update(path for path in TOP_LEVEL_PYTHON_FILES if path.exists())
    return sorted(paths)


def _read_source(path: Path) -> str:
    """读取 Python 源码，统一使用 UTF-8 编码。"""

    return path.read_text(encoding="utf-8")


def _relative(path: Path) -> str:
    """返回便于 pytest 失败信息阅读的仓库相对路径。"""

    return str(path.relative_to(PROJECT_ROOT))


def _imports_loguru_logger(tree: ast.AST) -> bool:
    """判断模块是否通过 loguru 导入 logger。"""

    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.module != "loguru":
            continue
        if any(alias.name == "logger" for alias in node.names):
            return True
    return False


def _imports_stdlib_logging(tree: ast.AST) -> bool:
    """判断模块是否导入 Python 标准库 logging。"""

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name == "logging" for alias in node.names):
                return True
        if isinstance(node, ast.ImportFrom) and node.module == "logging":
            return True
    return False


def _logger_call_count(tree: ast.AST) -> int:
    """统计 logger.<level>(...) 形式的日志调用数量。"""

    return sum(1 for node in ast.walk(tree) if _is_logger_call(node))


def _is_logger_call(node: ast.AST) -> bool:
    """判断 AST 节点是否为 loguru logger 调用。"""

    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "logger"
    )


def _sensitive_names_in_expression(expression: ast.AST) -> set[str]:
    """提取日志参数表达式中疑似敏感字段名。"""

    names: set[str] = set()

    for node in ast.walk(expression):
        candidate = ""
        if isinstance(node, ast.Name):
            candidate = node.id
        elif isinstance(node, ast.Attribute):
            candidate = node.attr
        elif isinstance(node, ast.keyword) and node.arg:
            candidate = node.arg

        lowered = candidate.lower()
        if any(part in lowered for part in SENSITIVE_NAME_PARTS):
            names.add(candidate)

    return names
