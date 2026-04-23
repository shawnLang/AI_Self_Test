"""命令行启动脚本。

该文件允许通过 ``python run.py`` 的方式启动 aiSelfTest 服务，
主要用于本地开发或未安装控制台脚本时的兜底入口。
"""

from aiSelfTest import main

if __name__ == "__main__":
    # 保持入口最小化，真实启动逻辑统一放在包级 main 中。
    main()
