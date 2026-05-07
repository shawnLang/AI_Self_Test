"""构建并打包项目的辅助脚本。

该脚本会把源码复制到临时打包目录，再调用 ``build_utils``
 中的构建流程生成可分发产物。
"""
import importlib.util
import os
import shutil
import sys
from pathlib import Path

# 忽略的文件
ignore_files = ['*.iml', 'setup_build.py', '.git*','CLAUDE.md','README.md']
# 忽略的 文件夹
ignore_folders = ['package', '__pycache__', '.git', '.idea', 'build', '*.egg-info', 'deploy', 'dist', 'lib','ui','.claude','.venv','.aiSelfTest']

# 需要编译的文件夹路径
root_path = Path(__file__).parent.resolve()

package_name = 'package'
package_path = root_path / package_name

build_py_path = root_path / 'build_utils.py'
build_utils = None
if not build_py_path.exists():
    # 打包流程依赖统一的构建工具模块，缺失时直接中断。
    raise RuntimeError(f"build_utils.py 路径不存在 : {build_py_path}")

spec = importlib.util.spec_from_file_location("build_utils", build_py_path)
build_utils = importlib.util.module_from_spec(spec)
sys.modules["build_utils"] = build_utils
spec.loader.exec_module(build_utils)


def run() -> None:
    """执行项目打包流程。

    流程包括清理旧的打包目录、复制源码以及调用实际构建逻辑。
    """
    if package_path.exists():
        shutil.rmtree(package_path)
    os.makedirs(package_path)
    # 先生成一份干净的打包工作目录，再由 build_utils 继续处理。
    build_utils.mv_to_packages(root_path, package_path, ignore_folders, ignore_files)
    build_utils.setup_build(package_path)


if __name__ == '__main__':
    run()
