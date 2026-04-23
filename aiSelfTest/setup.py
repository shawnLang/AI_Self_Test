"""项目打包入口脚本。

该脚本基于 ``setuptools`` 与 ``Cython`` 生成扩展模块，
并复用 ``build_utils`` 中的自定义构建规则。
"""
import importlib.util
import sys
from pathlib import Path

from Cython.Build import cythonize
from setuptools import setup

# Settings
FILE = Path(__file__).resolve()
PARENT = FILE.parent  # 根目录
# 编译忽略的文件
build_ignore = ['setup.py', 'setup_build.py', 'build_utils.py']

build_py_path = PARENT / 'build_utils.py'
build_utils = None
if not build_py_path.exists():
    # 构建规则统一放在 build_utils 中，找不到时无法继续打包。
    raise RuntimeError(f"build_utils.py 路径不存在 : {build_py_path}")

spec = importlib.util.spec_from_file_location("build_utils", build_py_path)
build_utils = importlib.util.module_from_spec(spec)
sys.modules["build_utils"] = build_utils
spec.loader.exec_module(build_utils)

# 修复 Windows 平台打包时 ``__init__.py`` 的导出符号问题。
build_utils.repair_windows_init()

python_files, extensions = build_utils.build(path=PARENT, build_ignore=build_ignore)

setup(
    name='aiSelfTest',
    ext_modules=cythonize(extensions, language_level='3', annotate=False),
    cmdclass={"build_py": build_utils.MyBuildPy, "install_lib": build_utils.MyInstallLib},
)
