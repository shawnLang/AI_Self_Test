"""构建并打包项目的辅助脚本。"""
import importlib.util
import os
import shutil
import sys
from pathlib import Path

# 忽略的文件
ignore_files = ['*.iml', 'setup_build.py', '.git*','CLAUDE.md','README.md']
# 忽略的 文件夹
ignore_folders = ['package', '__pycache__', '.git', '.idea', 'build', '*.egg-info', 'deploy', 'dist', 'lib','ui','.claude','.venv']

# 需要编译的文件夹路径
root_path = Path(__file__).parent.resolve()

package_name = 'package'
package_path = root_path / package_name

build_py_path = root_path / 'build_utils.py'
build_utils = None
if not build_py_path.exists():
    # 抛出运行错误异常
    raise RuntimeError(f"build_utils.py 路径不存在 : {build_py_path}")

spec = importlib.util.spec_from_file_location("build_utils", build_py_path)
build_utils = importlib.util.module_from_spec(spec)
sys.modules["build_utils"] = build_utils
spec.loader.exec_module(build_utils)


def run() -> None:
    """执行项目打包流程。"""
    if package_path.exists():
        shutil.rmtree(package_path)
    os.makedirs(package_path)
    # 复制文件到打包目录
    build_utils.mv_to_packages(root_path, package_path, ignore_folders, ignore_files)
    build_utils.setup_build(package_path)


if __name__ == '__main__':
    run()
