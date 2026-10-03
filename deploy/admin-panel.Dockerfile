FROM node:22-alpine AS build
WORKDIR /app/user_panel
COPY user_panel/package*.json ./
RUN npm ci
COPY user_panel/ ./
WORKDIR /app/admin_panel
COPY admin_panel/package*.json ./
RUN npm ci
COPY admin_panel/ ./
RUN npm run build
FROM nginx:1.28-alpine
COPY deploy/spa.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/admin_panel/dist/ /usr/share/nginx/html/shirin/
