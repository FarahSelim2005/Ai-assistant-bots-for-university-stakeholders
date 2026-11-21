# The frontend: built with Vite, then served by Caddy (which also forwards /api to the backend).
FROM node:22-alpine AS build
WORKDIR /web
COPY package*.json ./
RUN npm ci
COPY . .
# On the server the backend is under /api on the same address (see src/api.js).
ARG VITE_API_URL=/api
ARG VITE_PLATFORM_DOMAIN=
ENV VITE_API_URL=$VITE_API_URL VITE_PLATFORM_DOMAIN=$VITE_PLATFORM_DOMAIN
RUN npm run build

FROM caddy:2
COPY --from=build /web/dist /srv
