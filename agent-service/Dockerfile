FROM oven/bun:1.4.0 AS dependencies
WORKDIR /app
COPY package.json bun.lock ./
RUN bun install --frozen-lockfile --production

FROM oven/bun:1.4.0
WORKDIR /app
COPY --from=dependencies /app/node_modules ./node_modules
COPY package.json ./
COPY src ./src
USER bun
ENV ONYX_AGENT_SERVICE_HOST=0.0.0.0
EXPOSE 8091
CMD ["bun", "run", "start"]
