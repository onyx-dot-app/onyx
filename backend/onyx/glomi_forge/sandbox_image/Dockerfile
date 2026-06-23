# glomi-landing-page snapshot: Node + bun + Next.js template + Pi + python3.
FROM oven/bun:1-debian AS base

RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs npm python3 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN npm i -g @earendil-works/pi-coding-agent

COPY run_forge.py write_models_json.py /opt/glomi/

# Build context must provide web-template/ seeded from the existing Craft web output
# template before building this snapshot.
COPY web-template/ /workspace/src/

WORKDIR /workspace/src
RUN bun install
RUN mkdir -p /workspace/input /workspace/context /workspace/out /workspace/logs
