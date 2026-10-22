FROM node:20 AS build
WORKDIR /site
COPY . .
RUN npm ci && npm run build

FROM nginx:1.27
COPY --from=build /site/dist /usr/share/nginx/html
EXPOSE 80
