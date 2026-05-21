# 构建阶段
FROM node:20.19-alpine AS builder

WORKDIR /app

# 复制 package 文件
COPY package.json package-lock.json ./

# 安装依赖
RUN npm ci

# 复制源代码
COPY . .

ARG VITE_REGISTRATION_ENABLED=true
ENV VITE_REGISTRATION_ENABLED=$VITE_REGISTRATION_ENABLED

# 构建
RUN npm run build

# 运行阶段
FROM node:20.19-alpine

WORKDIR /app
ENV NODE_ENV=production
ENV FRONTEND_DIST_DIR=/app/dist
ENV FRONTEND_PORT=80
ENV USER_SERVICE_URL=http://user-service:8000
ENV MARKET_SERVICE_URL=http://market-service:8000
ENV ANALYSIS_SERVICE_URL=http://analysis-service:8000

# 复制构建产物和静态网关
COPY --from=builder /app/dist ./dist
COPY serve_frontend_static.mjs ./serve_frontend_static.mjs

# 健康检查
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD node -e "const http=require('http');const req=http.request({host:'127.0.0.1',port:80,path:'/health',timeout:2000},res=>process.exit(res.statusCode===200?0:1));req.on('error',()=>process.exit(1));req.end()"

EXPOSE 80

CMD ["node", "serve_frontend_static.mjs"]
