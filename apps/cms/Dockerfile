FROM node:24.11.0-bookworm-slim@sha256:76d0ed0ed93bed4f4376211e9d8fddac4d8b3fbdb54cc45955696001a3c91152
WORKDIR /app
ENV STRAPI_TELEMETRY_DISABLED=true STRAPI_DISABLE_UPDATE_NOTIFICATION=true
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
# No database, credentials or .env is needed to build the admin assets.
RUN NODE_ENV=production npm run build \
    && mkdir -p public/uploads .tmp database/migrations \
    && chown -R node:node /app/.strapi /app/public /app/.tmp /app/database
# All CMS dependencies are runtime dependencies in the current package.json.
# Keep one stage: no duplicate node_modules copy/layer or native compiler toolchain.
ENV NODE_ENV=production HOST=0.0.0.0 PORT=1337 STRAPI_TELEMETRY_DISABLED=true STRAPI_DISABLE_UPDATE_NOTIFICATION=true
USER node
EXPOSE 1337
HEALTHCHECK --interval=15s --timeout=5s --start-period=90s --retries=5 \
    CMD ["node", "-e", "fetch('http://127.0.0.1:1337/_health').then(r=>process.exit(r.status===204?0:1)).catch(()=>process.exit(1))"]
CMD ["npm", "run", "start"]
