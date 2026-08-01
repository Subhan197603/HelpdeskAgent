FROM node:24-alpine AS build

WORKDIR /workspace
RUN corepack enable
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json ./apps/web/package.json
COPY packages/api-client/package.json ./packages/api-client/package.json
COPY apps/web ./apps/web
COPY packages/api-client ./packages/api-client
COPY tsconfig.json ./tsconfig.json
RUN pnpm install --frozen-lockfile
ARG VITE_API_URL=http://127.0.0.1:8000
ENV VITE_API_URL=${VITE_API_URL}
RUN pnpm --filter @fusion-helpdesk/web build

FROM node:24-alpine

WORKDIR /app
RUN rm -rf /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/corepack \
    /usr/local/bin/npm /usr/local/bin/npx /usr/local/bin/corepack
COPY --from=build --chown=node:node /workspace/apps/web/dist ./dist
COPY --from=build --chown=node:node /workspace/apps/web/server.mjs ./server.mjs
USER node
EXPOSE 3000
CMD ["node", "server.mjs"]
