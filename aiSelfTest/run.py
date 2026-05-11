"""命令行启动脚本。

该文件允许通过 ``python run.py`` 的方式启动 aiSelfTest 服务，
主要用于本地开发或未安装控制台脚本时的兜底入口。
"""

from aiSelfTest.server import main

if __name__ == "__main__":
    # 开发启动保留 loguru 默认控制台输出，不配置部署文件日志。
    main(configure_file_logging=False)
