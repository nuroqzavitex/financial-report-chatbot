# Web image: Next.js standalone build. NEXT_PUBLIC_API_URL is inlined at build time and is the
# address the *browser* uses to reach the API, so it is the host-published port, not the
# compose service name.
FROM node:24-alpine AS deps
WORKDIR /web
RUN corepack enable && corepack prepare pnpm@9.15.0 --activate
COPY apps/web/package.json apps/web/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

FROM node:24-alpine AS build
WORKDIR /web
RUN corepack enable && corepack prepare pnpm@9.15.0 --activate
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
# empty: no sign-in; a Clerk publishable key turns it on (CLERK_SECRET_KEY is a run-time variable)
ARG NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL \
    NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=$NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY \
    NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /web/node_modules ./node_modules
COPY apps/web ./
RUN pnpm build

FROM node:24-alpine AS run
WORKDIR /web
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    HOSTNAME=0.0.0.0 \
    PORT=3000
COPY --from=build /web/.next/standalone ./
COPY --from=build /web/.next/static ./.next/static
EXPOSE 3000
CMD ["node", "server.js"]
