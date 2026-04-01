"use client";

import { Button, Text } from "@opal/components";
import { SvgDownload, SvgTextLines } from "@opal/icons";
import Modal from "@/refresh-components/Modal";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import CopyIconButton from "@/refresh-components/buttons/CopyIconButton";
import { useHookExecutionLogs } from "@/hooks/useHookExecutionLogs";
import { formatDateTimeLog } from "@/lib/dateUtils";
import { downloadFile } from "@/lib/download";
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

// Section header: "Past Hour ————" or "Older ————"
function SectionHeader({ label }: { label: string }) {
  return (
    <Section
      flexDirection="row"
      alignItems="center"
      height="fit"
      className="py-1"
    >
      <Text font="secondary-body" color="text-03">
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
      <span className="shrink-0 text-code-code">
        <Text font="secondary-mono-label" color="inherit" nowrap>
          {formatDateTimeLog(log.created_at)}
        </Text>
      </span>
      {/* 2. Error message */}
      <span className="flex-1 min-w-0 break-all whitespace-pre-wrap text-code-code">
        <Text font="secondary-mono" color="inherit">
          {log.error_message ?? "Unknown error"}
        </Text>
      </span>
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
  const { recentErrors, olderErrors, isLoading, error } = useHookExecutionLogs(
    hook.id,
    10
  );

  const totalLines = recentErrors.length + olderErrors.length;
  const allLogs = [...recentErrors, ...olderErrors];

  function getLogsText() {
    return allLogs
      .map(
        (log) =>
          `${formatDateTimeLog(log.created_at)} ${
            log.error_message ?? "Unknown error"
          }`
      )
      .join("\n");
  }

  function handleDownload() {
    downloadFile(`${hook.name}-errors.txt`, { content: getLogsText() });
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
          ) : error ? (
            <Text font="main-ui-body" color="text-03">
              Failed to load logs.
            </Text>
          ) : totalLines === 0 ? (
            <Text font="main-ui-body" color="text-03">
              No errors in the past 30 days.
            </Text>
          ) : (
            <>
              {recentErrors.length > 0 && (
                <>
                  <SectionHeader label="Past Hour" />
                  {recentErrors.map((log, idx) => (
                    <LogRow key={log.created_at + String(idx)} log={log} />
                  ))}
                </>
              )}
              {olderErrors.length > 0 && (
                <>
                  <SectionHeader label="Older" />
                  {olderErrors.map((log, idx) => (
                    <LogRow key={log.created_at + String(idx)} log={log} />
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
          <Text font="main-ui-body" color="text-03">
            {`${totalLines} ${totalLines === 1 ? "line" : "lines"}`}
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
