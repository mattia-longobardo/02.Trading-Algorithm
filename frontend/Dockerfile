# Build multi-stage per Next.js standalone (output: "standalone")

# Dipendenze # ------------------------------------------------------------
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

# Build # -----------------------------------------------------------------
FROM node:22-alpine AS builder
WORKDIR /app
ARG BACKEND_URL=http://trading-backend:8000
ENV NEXT_TELEMETRY_DISABLED=1 \
    BACKEND_URL=${BACKEND_URL}
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

# Runtime # ---------------------------------------------------------------
FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    HOSTNAME=0.0.0.0 \
    PORT=3000

COPY --from=builder --chown=node:node /app/.next/standalone ./
COPY --from=builder --chown=node:node /app/.next/static ./.next/static
COPY --from=builder --chown=node:node /app/public ./public

USER node
EXPOSE 3000
CMD ["node", "server.js"]
