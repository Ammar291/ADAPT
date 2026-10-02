# syntax=docker/dockerfile:1.7
# Build context: repository root (the app depends on packages/contracts).
FROM node:24-alpine AS build
WORKDIR /repo
COPY package.json package-lock.json ./
COPY packages/contracts/package.json packages/contracts/
COPY frontend/package.json frontend/
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund
COPY packages/contracts packages/contracts
COPY frontend frontend
ARG VITE_API_BASE_URL=/api
ARG VITE_DATA_MODE=auto
ARG VITE_SHOW_DEV_BADGE=false
ARG DEMO_MODE=false
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL \
    DEMO_MODE=$DEMO_MODE \
    VITE_DATA_MODE=$VITE_DATA_MODE \
    VITE_SHOW_DEV_BADGE=$VITE_SHOW_DEV_BADGE
RUN npm run build -w @adapt/frontend

FROM nginx:1.27-alpine
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /repo/frontend/dist /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s CMD wget -qO- http://127.0.0.1:8080/ >/dev/null || exit 1
