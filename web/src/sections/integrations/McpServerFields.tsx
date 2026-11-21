"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { InputSingleSelect, InputTypeIn, Tag, Text } from "@opal/components";
import { InputVertical, Section } from "@opal/layouts";
import { IconLoader } from "@opal/loaders";
import { FetchError } from "@/lib/fetcher";
import { streamMCPServerProbe } from "@/lib/mcp/svc";
import { SUGGESTED_MCP_PLUGINS } from "@/lib/plugins/catalog";
import type { MCPSetupProbeResult } from "@/lib/mcp/types";
import type { McpTransport } from "@/lib/integrations/types";
import { normalizedUrl } from "@/sections/integrations/signIn";

const TRANSPORTS: readonly McpTransport[] = ["STREAMABLE_HTTP", "SSE"];

type ProbeState =
  | { kind: "idle" }
  | { kind: "checking" }
  | { kind: "forbidden" }
  | { kind: "done"; result: MCPSetupProbeResult };

interface McpServerFieldsProps {
  serverUrl: string;
  transport: McpTransport;
  onServerUrlChange: (value: string) => void;
  onSuggestion: (name: string, url: string) => void;
  onTransportChange: (value: McpTransport) => void;
  onProbed: (result: MCPSetupProbeResult) => void;
  showErrors: boolean;
  disabled: boolean;
}

export default function McpServerFields({
  serverUrl,
  transport,
  onServerUrlChange,
  onSuggestion,
  onTransportChange,
  onProbed,
  showErrors,
  disabled,
}: McpServerFieldsProps) {
  const t = useTranslations("admin.integrations.add.mcp");
  const [probe, setProbe] = useState<ProbeState>({ kind: "idle" });
  const url = normalizedUrl(serverUrl);
  const onProbedRef = useRef(onProbed);
  useEffect(() => {
    onProbedRef.current = onProbed;
  });

  useEffect(() => {
    if (!url) {
      setProbe({ kind: "idle" });
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      setProbe({ kind: "checking" });
      let result: MCPSetupProbeResult;
      try {
        result = await streamMCPServerProbe(
          url,
          () => undefined,
          controller.signal
        );
      } catch (failure) {
        if (controller.signal.aborted) return;
        // Only admins can check a server. The add still works.
        if (failure instanceof FetchError && failure.status === 403) {
          setProbe({ kind: "forbidden" });
          return;
        }
        result = { kind: "unreachable", reason: "connection_failed" };
      }
      if (controller.signal.aborted) return;
      setProbe({ kind: "done", result });
      onProbedRef.current(result);
    }, 700);
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [url]);

  function probeMessage(result: MCPSetupProbeResult): string {
    switch (result.kind) {
      case "public":
        return t("probe.public", { count: result.tool_count });
      case "oauth":
        return t("probe.oauth");
      case "auth_unknown":
        return t("probe.authUnknown");
      case "unreachable":
        return t("probe.unreachable");
    }
  }

  return (
    <Section gap={4} alignItems="stretch" height="auto">
      <InputVertical title={t("suggested")}>
        <Section
          flexDirection="row"
          justifyContent="start"
          gap={1}
          wrap
          height="auto"
        >
          {SUGGESTED_MCP_PLUGINS.map((suggestion) => (
            <Tag
              key={suggestion.id}
              icon={suggestion.icon}
              title={suggestion.name}
              aria-pressed={serverUrl === suggestion.serverUrl}
              onClick={() =>
                onSuggestion(suggestion.name, suggestion.serverUrl)
              }
            />
          ))}
        </Section>
      </InputVertical>
      <InputVertical
        title={t("url.title")}
        error={showErrors && !url ? t("url.error") : undefined}
      >
        <InputTypeIn
          aria-label={t("url.title")}
          placeholder={t("url.placeholder")}
          value={serverUrl}
          variant={disabled ? "disabled" : "primary"}
          onChange={(event) => onServerUrlChange(event.target.value)}
        />
      </InputVertical>
      {probe.kind === "checking" && (
        <Section flexDirection="row" justifyContent="start" gap={2}>
          <IconLoader size={16} />
          <Text font="secondary-body" color="text-03">
            {t("probe.checking")}
          </Text>
        </Section>
      )}
      {probe.kind === "forbidden" && (
        <Text font="secondary-body" color="text-03">
          {t("probe.forbidden")}
        </Text>
      )}
      {probe.kind === "done" && (
        <Text
          font="secondary-body"
          color={probe.result.kind === "unreachable" ? "text-05" : "text-03"}
        >
          {probeMessage(probe.result)}
        </Text>
      )}
      <InputVertical title={t("transport.title")}>
        <InputSingleSelect
          placeholder={t("transport.title")}
          value={transport}
          disabled={disabled}
          options={TRANSPORTS.map((value) => ({
            value,
            title:
              value === "SSE"
                ? t("transport.sse")
                : t("transport.streamableHttp"),
          }))}
          onValueChange={(value) => {
            const next = TRANSPORTS.find((option) => option === value);
            if (next) onTransportChange(next);
          }}
        />
      </InputVertical>
    </Section>
  );
}
