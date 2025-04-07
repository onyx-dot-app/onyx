FROM node:20-alpine AS base

LABEL com.onyx.maintainer="founders@onyx.app"
LABEL com.onyx.description="This image is the web/frontend container of Onyx which \
contains code for both the Community and Enterprise editions of Onyx. If you do not \
have a contract or agreement with DanswerAI, you are not permitted to use the Enterprise \
Edition features outside of personal development or testing purposes. Please reach out to \
founders@onyx.app for more information. Please visit https://github.com/onyx-dot-app/onyx"

# Default ONYX_VERSION, typically overriden during builds by GitHub Actions.
ARG ONYX_VERSION=0.0.0-dev
ENV ONYX_VERSION=${ONYX_VERSION} 

RUN echo "ONYX_VERSION: ${ONYX_VERSION}"

# Step 1. Install dependencies only when needed
FROM base AS deps
# Check https://github.com/nodejs/docker-node/tree/b4117f9333da4138b03a546ec926ef50a31506c3#nodealpine to understand why libc6-compat might be needed.
RUN apk add --no-cache libc6-compat
WORKDIR /app

# Copy package files first to leverage Docker cache
COPY package.json package-lock.json ./

# Install dependencies with specific optimizations and caching
RUN --mount=type=cache,target=/root/.npm \
    npm config set registry https://registry.npmjs.org/ && \
    npm config set fetch-retries 3 && \
    npm config set fetch-retry-mintimeout 5000 && \
    npm config set fetch-retry-maxtimeout 10000 && \
    npm ci --prefer-offline --no-audit

# Step 2. Rebuild the source code only when needed
FROM base AS builder
WORKDIR /app

# Copy dependencies from deps stage
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# Add NODE_OPTIONS argument
ARG NODE_OPTIONS

# needed to get the `standalone` dir we expect later
ENV NEXT_PRIVATE_STANDALONE=true
ENV NEXT_TELEMETRY_DISABLED=1

# Environment variables must be present at build time
# https://github.com/vercel/next.js/discussions/14030
# NOTE: if you add something here, make sure to add it to the runner as well
ARG NEXT_PUBLIC_DISABLE_STREAMING
ENV NEXT_PUBLIC_DISABLE_STREAMING=${NEXT_PUBLIC_DISABLE_STREAMING}

ARG NEXT_PUBLIC_NEW_CHAT_DIRECTS_TO_SAME_PERSONA
ENV NEXT_PUBLIC_NEW_CHAT_DIRECTS_TO_SAME_PERSONA=${NEXT_PUBLIC_NEW_CHAT_DIRECTS_TO_SAME_PERSONA}

# allow user to specify custom feedback options
ARG NEXT_PUBLIC_POSITIVE_PREDEFINED_FEEDBACK_OPTIONS
ENV NEXT_PUBLIC_POSITIVE_PREDEFINED_FEEDBACK_OPTIONS=${NEXT_PUBLIC_POSITIVE_PREDEFINED_FEEDBACK_OPTIONS}

ARG NEXT_PUBLIC_NEGATIVE_PREDEFINED_FEEDBACK_OPTIONS
ENV NEXT_PUBLIC_NEGATIVE_PREDEFINED_FEEDBACK_OPTIONS=${NEXT_PUBLIC_NEGATIVE_PREDEFINED_FEEDBACK_OPTIONS}

ARG NEXT_PUBLIC_DEFAULT_SIDEBAR_OPEN
ENV NEXT_PUBLIC_DEFAULT_SIDEBAR_OPEN=${NEXT_PUBLIC_DEFAULT_SIDEBAR_OPEN}

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

# Optimize Next.js build with additional settings
ENV NEXT_SHARP_PATH=/app/node_modules/sharp
ENV NEXT_TURBO=1
ENV NEXT_RUNTIME_NODE_ENV=production

# Additional Next.js build optimizations
ENV NEXT_WEBPACK_USEPOLLING=false
ENV NEXT_WEBPACK_POLLING_INTERVAL=0
ENV NEXT_EXPERIMENTAL_TURBO=true
ENV NEXT_EXPERIMENTAL_TURBO_TRACE=true
ENV NEXT_EXPERIMENTAL_TURBO_LOADER=true

# Use NODE_OPTIONS in the build command with optimized settings and caching
RUN --mount=type=cache,target=/root/.next/cache \
    --mount=type=cache,target=/root/.cache/babel-loader \
    NODE_OPTIONS="--max-old-space-size=13152 --max-semi-space-size=64" \
    npx next build

# Step 3. Production image, copy all the files and run next
FROM base AS runner
WORKDIR /app

# Remove global node modules, since they are not needed by the actual app
# (all dependencies are copied over into the `/app` dir itself). These
# global modules may be outdated and trigger security scans.
RUN rm -rf /usr/local/lib/node_modules

# Disable automatic telemetry collection
ENV NEXT_TELEMETRY_DISABLED=1

# Don't run production as root
RUN addgroup --system --gid 1001 nodejs
RUN adduser --system --uid 1001 nextjs
USER nextjs

# Copy only necessary files from builder
COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

# Environment variables must be redefined at run time
# NOTE: if you add something here, make sure to add it to the builder as well
ARG NEXT_PUBLIC_DISABLE_STREAMING
ENV NEXT_PUBLIC_DISABLE_STREAMING=${NEXT_PUBLIC_DISABLE_STREAMING}

ARG NEXT_PUBLIC_NEW_CHAT_DIRECTS_TO_SAME_PERSONA
ENV NEXT_PUBLIC_NEW_CHAT_DIRECTS_TO_SAME_PERSONA=${NEXT_PUBLIC_NEW_CHAT_DIRECTS_TO_SAME_PERSONA}

# allow user to specify custom feedback options
ARG NEXT_PUBLIC_POSITIVE_PREDEFINED_FEEDBACK_OPTIONS
ENV NEXT_PUBLIC_POSITIVE_PREDEFINED_FEEDBACK_OPTIONS=${NEXT_PUBLIC_POSITIVE_PREDEFINED_FEEDBACK_OPTIONS}

ARG NEXT_PUBLIC_NEGATIVE_PREDEFINED_FEEDBACK_OPTIONS
ENV NEXT_PUBLIC_NEGATIVE_PREDEFINED_FEEDBACK_OPTIONS=${NEXT_PUBLIC_NEGATIVE_PREDEFINED_FEEDBACK_OPTIONS}

ARG NEXT_PUBLIC_THEME
ENV NEXT_PUBLIC_THEME=${NEXT_PUBLIC_THEME}

ARG NEXT_PUBLIC_DO_NOT_USE_TOGGLE_OFF_DANSWER_POWERED
ENV NEXT_PUBLIC_DO_NOT_USE_TOGGLE_OFF_DANSWER_POWERED=${NEXT_PUBLIC_DO_NOT_USE_TOGGLE_OFF_DANSWER_POWERED}

ARG NEXT_PUBLIC_DEFAULT_SIDEBAR_OPEN
ENV NEXT_PUBLIC_DEFAULT_SIDEBAR_OPEN=${NEXT_PUBLIC_DEFAULT_SIDEBAR_OPEN}

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

# Note: Don't expose ports here, Compose will handle that for us if necessary. 
# If you want to run this without compose, specify the ports to 
# expose via cli

CMD ["node", "server.js"]

