# 数据目录（ 日志 / 任务文件）
AI_SELF_TEST_DATA_DIR=./.aiSelfTest

# CORS 允许的源（逗号分隔）
AI_SELF_TEST_CORS_ORIGINS=http://localhost:5173,http://localhost:3000

# 数据库
DATABASE_URL="postgresql://eco:eco!%40%232024@192.168.1.30:8023/ai_self_test"

# Redis 配置
REDIS_URL="redis://:eco!%40%232026@192.168.1.30:8024/15"
# 任务执行数量
TASK_WORKER_CONCURRENCY=2
# 表示任务执行硬超时 6 小时
TASK_TIME_LIMIT_SECONDS=21600
# 表示任务执行软超时 5 小时 50 分钟
TASK_SOFT_TIME_LIMIT_SECONDS=21000
# 大模型聊天调用超时秒数（视频整帧识别建议 120-300）
MODEL_CHAT_TIMEOUT_SECONDS=300