# Convenience targets for the egress PoC.
#
# Compose layering:
#   base    -> proxy, broker, upstream, three networks
#   +explicit overlay   -> sandbox-explicit + sandbox-explicit-net
#   +transparent overlay -> sandbox-transparent + iptables-init
#
# We always run with BOTH overlays so the demo runner can hit both sandboxes
# in one pass.

COMPOSE_FILES := -f docker-compose.yml \
                 -f docker-compose.explicit.yml \
                 -f docker-compose.transparent.yml
COMPOSE := docker compose $(COMPOSE_FILES)

.PHONY: help up down build demo demo-explicit demo-transparent \
        shell-explicit shell-transparent logs-proxy logs-broker logs-upstream \
        ca clean

help:
	@echo "Targets:"
	@echo "  ca                 generate the Onyx CA (idempotent)"
	@echo "  build              build all images"
	@echo "  up                 ca + build + start everything"
	@echo "  down               stop and remove containers + volumes"
	@echo "  demo               run all demos against both sandboxes"
	@echo "  demo-explicit      run all demos against sandbox-explicit only"
	@echo "  demo-transparent   run all demos against sandbox-transparent only"
	@echo "  shell-explicit     drop into a shell inside sandbox-explicit"
	@echo "  shell-transparent  drop into a shell inside sandbox-transparent"
	@echo "  logs-proxy         tail proxy audit log (JSON lines on stdout)"
	@echo "  logs-broker        tail broker logs"
	@echo "  logs-upstream      tail mock-upstream logs"
	@echo "  clean              down + remove generated CA"

ca:
	@./ca/gen-ca.sh
	@# Sandbox image bakes the CA in; copy it into the build context.
	@cp ca/ca.crt sandbox/ca.crt

build: ca
	# Sandbox image is referenced by two services; build it once explicitly
	# to avoid a parallel-build race on the same tag.
	docker build -t egress-poc/sandbox:latest ./sandbox
	$(COMPOSE) build

up: build
	$(COMPOSE) up -d
	@echo ""
	@echo "Stack is up. Run 'make demo' to exercise both sandboxes."

down:
	$(COMPOSE) down --volumes --remove-orphans

demo:
	@./demos/runner.sh

demo-explicit:
	@for d in $$(ls demos/[0-9][0-9]_*.sh | sort); do bash "$$d" sandbox-explicit; done

demo-transparent:
	@for d in $$(ls demos/[0-9][0-9]_*.sh | sort); do bash "$$d" sandbox-transparent; done

shell-explicit:
	docker exec -it egress-poc-sandbox-explicit bash

shell-transparent:
	docker exec -it egress-poc-sandbox-transparent bash

logs-proxy:
	docker logs -f egress-poc-proxy

logs-broker:
	docker logs -f egress-poc-broker

logs-upstream:
	docker logs -f egress-poc-upstream

clean: down
	rm -f ca/ca.crt ca/ca.key ca/ca.key.enc sandbox/ca.crt
