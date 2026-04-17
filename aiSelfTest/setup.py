"""项目打包入口脚本。"""
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
    # 抛出运行错误异常
    raise RuntimeError(f"build_utils.py 路径不存在 : {build_py_path}")

spec = importlib.util.spec_from_file_location("build_utils", build_py_path)
build_utils = importlib.util.module_from_spec(spec)
sys.modules["build_utils"] = build_utils
spec.loader.exec_module(build_utils)

# 修复windows打包__init__.py 文件
build_utils.repair_windows_init()

python_files, extensions = build_utils.build(path=PARENT, build_ignore=build_ignore)

setup(
    name='aiSelfTest',
    ext_modules=cythonize(extensions, language_level='3', annotate=False),
    cmdclass={"build_py": build_utils.MyBuildPy, "install_lib": build_utils.MyInstallLib},
)
