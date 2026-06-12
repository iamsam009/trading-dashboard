# ─── Builder Stage ────────────────────────────────────
FROM node:20-alpine AS builder

WORKDIR /app

COPY package.json package-lock.json* ./

# Install dependencies (ci for reproducible builds)
RUN npm ci

COPY . .

# Ensure public directory exists (Next.js requires it for static assets)
RUN mkdir -p /app/public

# Build Next.js (standalone output for lean production image)
ARG NEXT_PUBLIC_API_BASE_URL=http://backend:8000
ARG NEXT_PUBLIC_WS_URL=ws://backend:8000/ws
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}
ENV NEXT_PUBLIC_WS_URL=${NEXT_PUBLIC_WS_URL}

RUN npm run build

# ─── Production Stage ──────────────────────────────────
FROM node:20-alpine AS runner

WORKDIR /app

ENV NODE_ENV=production

RUN addgroup --system --gid 1001 nodejs && \
    adduser --system --uid 1001 nextjs

# Copy only the standalone output
COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs

EXPOSE 3000

ENV PORT=3000
ENV HOSTNAME=0.0.0.0

CMD ["node", "server.js"]