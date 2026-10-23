FROM node:22-alpine AS build

WORKDIR /web
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# Vite resolves these values during the static build, not at runtime.
ARG VITE_API_URL=http://127.0.0.1:8001
ARG VITE_API_KEY=local-dev-key
ENV VITE_API_URL=${VITE_API_URL} \
    VITE_API_KEY=${VITE_API_KEY}
RUN npm run build

FROM nginx:stable-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /web/dist /usr/share/nginx/html
EXPOSE 80
