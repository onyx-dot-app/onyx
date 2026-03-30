"use client";

import { Button } from "@opal/components";
import { SvgDownload, SvgTextLines } from "@opal/icons";
import Modal from "@/refresh-components/Modal";
import Text from "@/refresh-components/texts/Text";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import CopyIconButton from "@/refresh-components/buttons/CopyIconButton";
import { useHookExecutionLogs } from "@/hooks/useHookExecutionLogs";
import { Section } from "@/layouts/general-layouts";
import type {
  HookExecutionRecord,
  HookPointMeta,
  HookResponse,
} from "@/refresh-pages/admin/HooksPage/interfaces";

interface HookLogsModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  hook: HookResponse;
  spec: HookPointMeta | undefined;
}

function formatTimestamp(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}/${pad(d.getMonth() + 1)}/${pad(d.getDate())} ${pad(
    d.getHours()
  )}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

// Section header: "Past Hour ————" or "Older ————"
function SectionHeader({ label }: { label: string }) {
  return (
    <Section
      flexDirection="row"
      alignItems="center"
      height="fit"
      className="py-1"
    >
      <Text secondaryBody text03 className="px-0.5">
        {label}
      </Text>
      <div className="flex-1 ml-2 border-t border-border-02" />
    </Section>
  );
}

function LogRow({ log }: { log: HookExecutionRecord }) {
  return (
    <Section
      flexDirection="row"
      justifyContent="start"
      alignItems="start"
      gap={0.5}
      height="fit"
      className="py-2"
    >
      {/* 1. Timestamp */}
      <Text secondaryMonoLabel text04 nowrap className="shrink-0 px-0.5">
        {formatTimestamp(log.created_at)}
      </Text>
      {/* 2. Error message */}
      <Text secondaryMono text04 className="flex-1 min-w-0 break-all px-0.5">
        {log.error_message ?? "Unknown error"}
      </Text>
      {/* 3. Copy button */}
      <Section width="fit" height="fit" alignItems="center">
        <CopyIconButton size="xs" getCopyText={() => log.error_message ?? ""} />
      </Section>
    </Section>
  );
}

export default function HookLogsModal({
  open,
  onOpenChange,
  hook,
  spec,
}: HookLogsModalProps) {
  const { recentErrors, olderErrors, isLoading } = useHookExecutionLogs(
    hook.id,
    10
  );

  const totalLines = recentErrors.length + olderErrors.length;
  const allLogs = [...recentErrors, ...olderErrors];

  function getLogsText() {
    return allLogs
      .map(
        (log) =>
          `${formatTimestamp(log.created_at)} ${
            log.error_message ?? "Unknown error"
          }`
      )
      .join("\n");
  }

  function handleDownload() {
    const blob = new Blob([getLogsText()], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${hook.name}-errors.txt`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <Modal open={open} onOpenChange={onOpenChange}>
      <Modal.Content width="md" height="fit">
        <Modal.Header
          icon={(props) => <SvgTextLines {...props} />}
          title="Recent Errors"
          description={`Hook: ${hook.name} • Hook Point: ${
            spec?.display_name ?? hook.hook_point
          }`}
          onClose={() => onOpenChange(false)}
        />
        <Modal.Body>
          {isLoading ? (
            <Section justifyContent="center" height="fit" className="py-6">
              <SimpleLoader />
            </Section>
          ) : totalLines === 0 ? (
            <Text mainUiBody text03>
              No errors in the past 30 days.
            </Text>
          ) : (
            <>
              {recentErrors.length > 0 && (
                <>
                  <SectionHeader label="Past Hour" />
                  {recentErrors.map((log, idx) => (
                    <LogRow key={idx} log={log} />
                  ))}
                </>
              )}
              {olderErrors.length > 0 && (
                <>
                  <SectionHeader label="Older" />
                  {olderErrors.map((log, idx) => (
                    <LogRow key={idx} log={log} />
                  ))}
                </>
              )}
            </>
          )}
        </Modal.Body>
        <Section
          flexDirection="row"
          justifyContent="between"
          alignItems="center"
          padding={0.5}
          className="bg-background-tint-01"
        >
          <Text mainUiBody text03>
            {totalLines} {totalLines === 1 ? "line" : "lines"}
          </Text>
          <Section
            flexDirection="row"
            alignItems="center"
            width="fit"
            gap={0.25}
            padding={0.25}
            className="rounded-xl bg-background-tint-00"
          >
            <CopyIconButton
              size="sm"
              tooltip="Copy"
              getCopyText={getLogsText}
            />
            <Button
              prominence="tertiary"
              size="sm"
              icon={SvgDownload}
              tooltip="Download"
              onClick={handleDownload}
            />
          </Section>
        </Section>
      </Modal.Content>
    </Modal>
  );
}
