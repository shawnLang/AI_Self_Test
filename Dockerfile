FROM node:20-slim

WORKDIR /app

# 安装 better-sqlite3 编译所需的依赖
RUN apt-get update && apt-get install -y python3 build-essential && rm -rf /var/lib/apt/lists/*

COPY package.json package-lock.json ./
RUN npm install

COPY . .

EXPOSE 3000 3001

CMD ["npm", "run", "dev"]
