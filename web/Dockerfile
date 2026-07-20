# Registry prefix for the bun binary source below. Defaults to Docker Hub; CI overrides it to
# the ECR pull-through cache to dodge rate limits. Applies only to `bun_source` -- the DHI Node
# bases come from dhi.io, a separate registry not served by the cache (see the FROM lines below).
ARG BASE_IMAGE_REGISTRY=docker.io

# bun binary source, in its own stage because buildx only expands the registry ARG in a FROM,
# not in `COPY --from=`. Use the glibc (Debian) build so it runs on the glibc DHI node images.
FROM ${BASE_IMAGE_REGISTRY}/oven/bun:1 AS bun_source

# Build stage. The DHI "-dev" variant runs as root and ships a shell, apt, and npm/npx.
# Refresh the digest with: docker buildx imagetools inspect dhi.io/node:24-debian13-dev
FROM dhi.io/node:24-debian13-dev@sha256:25a83f18150669e9ce3c9437327add4d75ae4ea26cbdb5e8747b66d3b74a567a AS builder
COPY --from=bun_source /usr/local/bin/bun /usr/local/bin/bun
COPY --from=bun_source /usr/local/bin/bunx /usr/local/bin/bunx
WORKDIR /app

# Copy package files + the full opal AND shared workspace sources so their `prepare`
# lifecycle hooks (which run during `bun install` for workspace packages) can build
# `dist/` artifacts before Next.js resolves package exports. opal's tsconfig
# extends web's `tsconfig.json`, so that file must also be present at install
# time for the DTS build to succeed. (`lib/shared` uses a standalone tsconfig and
# builds its design tokens + types via Style Dictionary + tsc in its own `prepare`.)
COPY package.json bun.lock tsconfig.json ./
COPY lib/opal/ ./lib/opal/
COPY lib/shared/ ./lib/shared/

# Install dependencies. opal's `prepare` script builds dist/ as part of install.
RUN bun install --frozen-lockfile

# pull in remaining source code
COPY . .

# needed to get the `standalone` dir we expect later
ENV NEXT_PRIVATE_STANDALONE=true

# Disable automatic telemetry collection
ENV NEXT_TELEMETRY_DISABLED=1

# Environment variables must be present at build time
# https://github.com/vercel/next.js/discussions/14030
# NOTE: if you add something here, make sure to add it to the runner as well


ARG NEXT_PUBLIC_THEME
ENV NEXT_PUBLIC_THEME=${NEXT_PUBLIC_THEME}

ARG NEXT_PUBLIC_DO_NOT_USE_TOGGLE_OFF_DANSWER_POWERED
ENV NEXT_PUBLIC_DO_NOT_USE_TOGGLE_OFF_DANSWER_POWERED=${NEXT_PUBLIC_DO_NOT_USE_TOGGLE_OFF_DANSWER_POWERED}

ARG NEXT_PUBLIC_DISABLE_LOGOUT
ENV NEXT_PUBLIC_DISABLE_LOGOUT=${NEXT_PUBLIC_DISABLE_LOGOUT}

ARG NEXT_PUBLIC_CUSTOM_REFRESH_URL
ENV NEXT_PUBLIC_CUSTOM_REFRESH_URL=${NEXT_PUBLIC_CUSTOM_REFRESH_URL}

ARG NEXT_PUBLIC_POSTHOG_KEY
ARG NEXT_PUBLIC_POSTHOG_HOST
ENV NEXT_PUBLIC_POSTHOG_KEY=${NEXT_PUBLIC_POSTHOG_KEY}
ENV NEXT_PUBLIC_POSTHOG_HOST=${NEXT_PUBLIC_POSTHOG_HOST}

ARG NEXT_PUBLIC_CLOUD_ENABLED
ENV NEXT_PUBLIC_CLOUD_ENABLED=${NEXT_PUBLIC_CLOUD_ENABLED}

# WEB_FRAME_PROTECTION_ENABLED is read at runtime (web/src/proxy.ts), not at
# build — it's set on the runner stage, not here.

ARG NEXT_PUBLIC_SENTRY_DSN
ENV NEXT_PUBLIC_SENTRY_DSN=${NEXT_PUBLIC_SENTRY_DSN}

ARG NEXT_PUBLIC_GTM_ENABLED
ENV NEXT_PUBLIC_GTM_ENABLED=${NEXT_PUBLIC_GTM_ENABLED}

ARG NEXT_PUBLIC_FORGOT_PASSWORD_ENABLED
ENV NEXT_PUBLIC_FORGOT_PASSWORD_ENABLED=${NEXT_PUBLIC_FORGOT_PASSWORD_ENABLED}

ARG NEXT_PUBLIC_INCLUDE_ERROR_POPUP_SUPPORT_LINK
ENV NEXT_PUBLIC_INCLUDE_ERROR_POPUP_SUPPORT_LINK=${NEXT_PUBLIC_INCLUDE_ERROR_POPUP_SUPPORT_LINK}

ARG NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY
ENV NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY=${NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY}

ARG NEXT_PUBLIC_RECAPTCHA_SITE_KEY
ENV NEXT_PUBLIC_RECAPTCHA_SITE_KEY=${NEXT_PUBLIC_RECAPTCHA_SITE_KEY}

ARG SENTRY_RELEASE
ENV SENTRY_RELEASE=${SENTRY_RELEASE}

# Add NODE_OPTIONS argument
ARG NODE_OPTIONS

# SENTRY_AUTH_TOKEN is injected via BuildKit secret mount so it is never written
# to any image layer, build cache, or registry manifest.
# Use NODE_OPTIONS in the build command
RUN --mount=type=secret,id=sentry_auth_token \
    if [ -f /run/secrets/sentry_auth_token ]; then \
        export SENTRY_AUTH_TOKEN="$(cat /run/secrets/sentry_auth_token)"; \
    fi && \
    NODE_OPTIONS="${NODE_OPTIONS}" npx next build

# Runtime stage. The DHI runtime variant is near-distroless: no shell or package manager, runs
# as the non-root `node` user (uid 1000) with WORKDIR /app pre-set.
# Refresh the digest with: docker buildx imagetools inspect dhi.io/node:24-debian13
FROM dhi.io/node:24-debian13@sha256:805278f24c1146c6d3c96577b6256f8f97c43196fff88315fe3291a1ce118ddd AS runner

LABEL com.onyx.maintainer="founders@onyx.app"
LABEL com.onyx.description="This image is the web/frontend container of Onyx which \
contains code for both the Community and Enterprise editions of Onyx. If you do not \
have a contract or agreement with DanswerAI, you are not permitted to use the Enterprise \
Edition features outside of personal development or testing purposes. Please reach out to \
founders@onyx.app for more information. Please visit https://github.com/onyx-dot-app/onyx"

WORKDIR /app

# Not needed, set by compose
# ENV NODE_ENV production

# Disable automatic telemetry collection
ENV NEXT_TELEMETRY_DISABLED=1

# `/app` is root-owned, so re-own build artifacts to `node` on copy.
COPY --from=builder --chown=node:node /app/public ./public

# Automatically leverage output traces to reduce image size
# https://nextjs.org/docs/advanced-features/output-file-tracing
COPY --from=builder --chown=node:node /app/.next/standalone ./
COPY --from=builder --chown=node:node /app/.next/static ./.next/static

# Environment variables must be redefined at run time
# NOTE: if you add something here, make sure to add it to the builder as well


# allow user to specify custom feedback options
ARG NEXT_PUBLIC_THEME
ENV NEXT_PUBLIC_THEME=${NEXT_PUBLIC_THEME}

ARG NEXT_PUBLIC_DO_NOT_USE_TOGGLE_OFF_DANSWER_POWERED
ENV NEXT_PUBLIC_DO_NOT_USE_TOGGLE_OFF_DANSWER_POWERED=${NEXT_PUBLIC_DO_NOT_USE_TOGGLE_OFF_DANSWER_POWERED}

ARG NEXT_PUBLIC_DISABLE_LOGOUT
ENV NEXT_PUBLIC_DISABLE_LOGOUT=${NEXT_PUBLIC_DISABLE_LOGOUT}

ARG NEXT_PUBLIC_CUSTOM_REFRESH_URL
ENV NEXT_PUBLIC_CUSTOM_REFRESH_URL=${NEXT_PUBLIC_CUSTOM_REFRESH_URL}

ARG NEXT_PUBLIC_POSTHOG_KEY
ARG NEXT_PUBLIC_POSTHOG_HOST
ENV NEXT_PUBLIC_POSTHOG_KEY=${NEXT_PUBLIC_POSTHOG_KEY}
ENV NEXT_PUBLIC_POSTHOG_HOST=${NEXT_PUBLIC_POSTHOG_HOST}

ARG NEXT_PUBLIC_CLOUD_ENABLED
ENV NEXT_PUBLIC_CLOUD_ENABLED=${NEXT_PUBLIC_CLOUD_ENABLED}

# frame-ancestors clickjacking protection, read at runtime by web/src/proxy.ts.
# The build arg only seeds the image default (cloud builds pass false); the
# container environment can override it without a rebuild.
ARG WEB_FRAME_PROTECTION_ENABLED
ENV WEB_FRAME_PROTECTION_ENABLED=${WEB_FRAME_PROTECTION_ENABLED}

ARG NEXT_PUBLIC_SENTRY_DSN
ENV NEXT_PUBLIC_SENTRY_DSN=${NEXT_PUBLIC_SENTRY_DSN}

ARG NEXT_PUBLIC_GTM_ENABLED
ENV NEXT_PUBLIC_GTM_ENABLED=${NEXT_PUBLIC_GTM_ENABLED}

ARG NEXT_PUBLIC_FORGOT_PASSWORD_ENABLED
ENV NEXT_PUBLIC_FORGOT_PASSWORD_ENABLED=${NEXT_PUBLIC_FORGOT_PASSWORD_ENABLED}

ARG NEXT_PUBLIC_INCLUDE_ERROR_POPUP_SUPPORT_LINK
ENV NEXT_PUBLIC_INCLUDE_ERROR_POPUP_SUPPORT_LINK=${NEXT_PUBLIC_INCLUDE_ERROR_POPUP_SUPPORT_LINK}

ARG NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY
ENV NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY=${NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY}

ARG NEXT_PUBLIC_RECAPTCHA_SITE_KEY
ENV NEXT_PUBLIC_RECAPTCHA_SITE_KEY=${NEXT_PUBLIC_RECAPTCHA_SITE_KEY}

ARG SENTRY_RELEASE
ENV SENTRY_RELEASE=${SENTRY_RELEASE}

# Default ONYX_VERSION, typically overridden during builds by GitHub Actions.
ARG ONYX_VERSION=0.0.0-dev
ENV ONYX_VERSION=${ONYX_VERSION}

# Note: Don't expose ports here, Compose will handle that for us if necessary.
# If you want to run this without compose, specify the ports to
# expose via cli

# Next.js standalone server.js reads HOSTNAME to decide what to bind to.
# Docker auto-sets HOSTNAME to the container ID, which makes Next bind to that
# name only — breaking loopback healthchecks. Force 0.0.0.0 instead.
ENV HOSTNAME="0.0.0.0"

# The DHI runtime image sets no default ENTRYPOINT, so invoke node explicitly.
CMD ["node", "server.js"]
