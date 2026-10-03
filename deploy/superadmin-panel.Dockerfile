FROM node:22-alpine AS build
WORKDIR /app/user_panel
COPY user_panel/package*.json ./
RUN npm ci
COPY user_panel/ ./
WORKDIR /app/superadmin_panel
COPY superadmin_panel/package*.json ./
RUN npm ci
COPY superadmin_panel/ ./
RUN npm run build
FROM nginx:1.28-alpine
COPY deploy/superadmin-spa.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/superadmin_panel/dist/ /usr/share/nginx/html/shirin/superadmin/
