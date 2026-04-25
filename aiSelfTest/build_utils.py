"""构建与打包辅助工具函数。"""
import fnmatch
import os
import platform
import shutil
import subprocess
import sys
import sysconfig
from distutils.command.build_ext import build_ext
from distutils.extension import Extension
from pathlib import Path
from typing import List, Sequence, Tuple

from setuptools import Command
from setuptools.command.build_py import build_py
from setuptools.command.install_lib import install_lib

try:
    from smbclient import makedirs, register_session
    from smbclient import shutil as smb_shutil
except ImportError as exc:  # pragma: no cover - 可选依赖
    makedirs = None
    register_session = None
    smb_shutil = None
    _SMB_IMPORT_ERROR = exc
else:
    _SMB_IMPORT_ERROR = None

smb_user = "shawn"
smb_password = "123456"
smb_server = '192.168.1.20'


def glob_build(name: str, build_ignore: Sequence[str]) -> bool:
    """判断文件名是否在编译忽略列表中。"""
    for ignore in build_ignore:
        if fnmatch.fnmatch(name, ignore):
            return True
    return False


def get_bm_info() -> str:
    """读取算能板卡信息（可选）。"""
    try:
        info = subprocess.run("bm_get_basic_info", shell=True, capture_output=True, check=True,
                              encoding='utf-8').stdout.strip()
        if info and len(str(info).strip()) > 0:
            return info
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        pass
    return ""


def is_bm1688() -> bool:
    """判断是否为 BM1688 平台。"""
    bm_info = get_bm_info()
    return "bm1688" in bm_info or "BM1688" in bm_info


def is_bm1684() -> bool:
    """判断是否为 BM1684 平台。"""
    bm_info = get_bm_info()
    return "bm1684" in bm_info or "BM1684" in bm_info


def is_jetson() -> bool:
    """判断是否为 Jetson 平台。"""
    try:
        info = subprocess.run("jetson_release -sv", shell=True, capture_output=True, check=True,
                              encoding='utf-8').stdout.strip()
        if info and len(str(info).strip()) > 0:
            return True
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        pass
    return False


def get_py_version(_build: bool = True) -> str:
    """获取 Python ABI 版本标识。"""
    py_version_info = sys.version_info
    if _build:
        py_version = f"cp{py_version_info.major}{py_version_info.minor}"
    else:
        py_version = "py"

    return py_version


def get_sys_version() -> str:
    """获取平台 wheel 标识字符串。"""
    # 获取系统信息
    system_platform = platform.system().lower()
    machine = platform.machine().lower()
    if system_platform == "windows":
        sys_version = "win_amd64" if machine == "amd64" else "win32"
    elif system_platform == "linux":
        if machine in ("aarch64", "arm64"):
            sys_version = "linux_aarch64"
        else:
            sys_version = "linux_x86_64"
    else:
        sys_version = f"{system_platform}_{machine}"

    return sys_version


def get_system() -> str:
    """获取自定义系统标识（用于打包与发布）。"""
    # 获取系统信息
    system_platform = platform.system().lower()
    machine = platform.machine().lower()
    system_info = system_platform
    if system_platform == "linux":
        if machine in ("aarch64", "arm64"):
            if is_jetson():
                system_info = "nvidia"
            elif is_bm1684():
                system_info = "sophon1684"
            elif is_bm1688():
                system_info = "sophon1688"
        else:
            system_info = "linux"

    return system_info


def build(path: Path, build_ignore: Sequence[str]) -> Tuple[List[str], List[Extension]]:
    """扫描源码目录并生成 Cython 编译配置。"""
    python_files = []
    extensions = []
    # 需要排除编译的目录（alembic 需要保持原始 Python 文件）
    exclude_dirs = ['alembic', '.venv', 'venv', 'env', '__pycache__']

    for dir_path, dir_list, file_list in os.walk(path.as_posix()):
        dir_path = Path(dir_path)

        # 检查当前目录是否在排除列表中
        relative_path = dir_path.relative_to(path)
        if any(part in exclude_dirs for part in relative_path.parts):
            continue

        for file in file_list:
            if fnmatch.fnmatch(file, '*.py') and not glob_build(file, build_ignore):
                file_path = (dir_path / file).as_posix()
                python_files.append(file_path)
                e_key = file_path.replace(path.as_posix(), '')[1:]
                e_name = e_key.replace('.py', '').replace('/', '.')

                extensions.append(Extension(e_name, [e_key]))

    return python_files, extensions


def repair_windows_init() -> None:
    """修复 Windows 下 distutils 的导出符号问题。"""
    if "windows" in platform.platform().lower():
        def get_export_symbols_fixed(self, ext: Extension) -> list:
            pass  # return [] also does the job!

        # replace wrong version with the fixed:
        build_ext.get_export_symbols = get_export_symbols_fixed


class MyBuildPy(build_py, Command):
    """自定义 build_py，过滤已编译的模块。"""

    def find_package_modules(self, package: str, package_dir: str) -> List[Tuple[str, str, str]]:
        ext_suffix = sysconfig.get_config_var('EXT_SUFFIX') or '.so'
        modules = super().find_package_modules(package, package_dir)
        filtered_modules = []
        for (pkg, mod, filepath) in modules:
            if os.path.exists(filepath.replace('.py', ext_suffix)):
                continue
            print(f'2 {"*" * 30} {pkg, mod, filepath}')
            filtered_modules.append((pkg, mod, filepath,))

        return filtered_modules


class MyInstallLib(install_lib, Command):
    """自定义 install_lib，移除已编译的源文件。"""

    def install(self) -> None:
        if os.path.isdir(self.build_dir):
            ext_suffix = sysconfig.get_config_var('EXT_SUFFIX') or '.so'
            for dir_path, dir_list, file_list in os.walk(self.build_dir):
                for file in file_list:
                    file_path = os.path.join(dir_path, file)
                    ext_file_path = file_path.replace('.py', ext_suffix)
                    if file_path.endswith('.py') and os.path.exists(ext_file_path):
                        print(f'3 {"*" * 30} delete file: {file_path}')
                        os.remove(file_path)
                    if file_path.endswith('.lib') or file_path.endswith('.exp'):
                        print(f'3 {"*" * 30} delete file: {file_path}')
                        os.remove(file_path)

        super().install()


def get_smb_path() -> str:
    """拼接 SMB 共享路径。"""
    py_version = get_py_version()
    system_info = get_system()
    if 'sophon' in system_info:
        system_info = "sophon"
    return f"\\\\{smb_server}\\whl\\{system_info}\\{py_version}\\"


def glob_folders(path: Path, ignore_folders: Sequence[str]) -> bool:
    """判断目录是否在忽略列表中。"""
    for ignore in ignore_folders:
        is_ignore = fnmatch.fnmatch(path.as_posix(), ignore)
        ignore = f'*{os.path.sep}' + ignore
        is_ignore1 = fnmatch.fnmatch(path.as_posix(), ignore)
        is_ignore2 = fnmatch.fnmatch(path.as_posix(), ignore + f'{os.path.sep}*')
        if is_ignore or is_ignore1 or is_ignore2:
            return True
    return False


def glob_files(name: str, ignore_files: Sequence[str]) -> bool:
    """判断文件名是否在忽略列表中。"""
    for ignore in ignore_files:
        if fnmatch.fnmatch(name, ignore):
            return True
    return False


def mv_to_packages(
    root_path: Path,
    package_path: Path,
    ignore_folders: Sequence[str],
    ignore_files: Sequence[str],
) -> None:
    """复制源码到打包目录，并按忽略规则筛选。"""
    # 复制自己
    package_path.mkdir(parents=True, exist_ok=True)
    build_utils_py = Path(__file__)
    print(f'复制文件: {build_utils_py} -> {package_path}')
    shutil.copyfile(build_utils_py, package_path / build_utils_py.name)
    for dir_path, dir_list, file_list in os.walk(root_path):
        dir_path = Path(dir_path)
        if dir_path != root_path and glob_folders(dir_path, ignore_folders):
            continue
        move_folder_path = Path(dir_path.as_posix().replace(root_path.as_posix(), package_path.as_posix()))
        if not move_folder_path.exists():
            os.makedirs(move_folder_path)
        for file in file_list:
            file_path = dir_path / file
            if glob_files(file, ignore_files):
                continue
            move_file_path = move_folder_path / file
            print(f'复制文件: {file_path} -> {move_file_path}')
            shutil.copyfile(file_path, move_file_path)


def setup_build(package_path: Path) -> None:
    """构建 wheel 并上传到 SMB 共享目录。"""
    if register_session is None or smb_shutil is None:
        raise RuntimeError("缺少 smbclient 依赖，无法上传构建产物。") from _SMB_IMPORT_ERROR
    if platform.system() == 'Windows':
        encoding = 'gbk'
        command = f'python -m build --wheel'
    else:
        encoding = 'utf-8'
        command = f'python3 -m build --wheel'
    process = subprocess.Popen(command, cwd=package_path, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    # 监听命令的输出和错误信息
    while True:
        output = process.stdout.readline()
        if output == b'' and process.poll() is not None:
            break
        if output:
            try:
                decoded_output = output.decode(encoding)
            except UnicodeDecodeError:
                decoded_output = output.decode('utf-8', errors='ignore')
            print(decoded_output, end='' if decoded_output[-1] == '\n' else '\n')
    error = process.stderr.read()
    if error:
        try:
            error_msg = error.decode(encoding)
        except UnicodeDecodeError:
            error_msg = error.decode('utf-8', errors='ignore')
        print('Error:', error_msg)
    if process.poll() == 0:
        print('构建成功')
        package_dist_path = package_path / 'dist'
        if package_dist_path.exists():
            # 注册SMB会话（需要替换为实际的服务器信息）
            register_session(smb_server, username=smb_user, password=smb_password)
            smb_path = get_smb_path()
            # 确保远程目录存在
            try:
                # 尝试创建远程目录（如果smbclient支持）
                if makedirs is None:
                    raise RuntimeError("缺少 smbclient 依赖，无法创建远程目录。") from _SMB_IMPORT_ERROR
                makedirs(smb_path, exist_ok=True)
            except Exception as e:
                print(f"创建远程目录失败（可能已存在）: {e}")
            for file in package_dist_path.glob('**/*.whl'):
                # 上传到SMB共享目录
                smb_full_path = smb_path + '\\' + file.name
                smb_shutil.copyfile(file, smb_full_path)
                print(f'上传到共享目录: {file} -> {smb_full_path}')
    else:
        print('构建失败')
    shutil.rmtree(package_path)
