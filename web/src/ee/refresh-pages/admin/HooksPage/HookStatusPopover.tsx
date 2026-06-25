"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useCreateModal } from "@/refresh-components/contexts/ModalContext";
import { noProp } from "@/lib/utils";
import { formatDateTimeLog } from "@/lib/dateUtils";
import { Button, Divider, Text } from "@opal/components";
import { Content } from "@opal/layouts";
import LineItem from "@/refresh-components/buttons/LineItem";
import { Popover } from "@opal/components";
import { Section } from "@/layouts/general-layouts";
import {
  SvgAlertTriangle,
  SvgCheckCircle,
  SvgMaximize2,
  SvgXOctagon,
  SvgSimpleLoader,
} from "@opal/icons";
import { CopyButton } from "@opal/components";
import { Hoverable } from "@opal/core";
import { useHookExecutionLogs } from "@/ee/hooks/useHookExecutionLogs";
import HookLogsModal from "@/ee/refresh-pages/admin/HooksPage/HookLogsModal";
import type {
  HookPointMeta,
  HookResponse,
} from "@/ee/refresh-pages/admin/HooksPage/interfaces";
import { cn } from "@opal/utils";

function ErrorLogRow({
  log,
  group,
}: {
  log: { created_at: string; error_message: string | null };
  group: string;
}) {
  const { t } = useTranslation();
  return (
    <Hoverable.Root group={group}>
      <Section
        flexDirection="column"
        justifyContent="start"
        alignItems="start"
        gap={0.25}
        padding={0.25}
        height="fit"
      >
        <Section
          flexDirection="row"
          justifyContent="between"
          alignItems="center"
          gap={0}
          height="fit"
        >
          <span className="text-code-code">
            <Text font="secondary-mono-label" color="inherit">
              {formatDateTimeLog(log.created_at)}
            </Text>
          </span>
          <Hoverable.Item group={group} variant="appear-on-hover">
            <CopyButton size="xs" getCopyText={() => log.error_message ?? ""} />
          </Hoverable.Item>
        </Section>
        <span className="break-all">
          <Text font="secondary-mono" color="text-03">
            {log.error_message ?? t("admin.hooks.logs_unknown_error")}
          </Text>
        </span>
      </Section>
    </Hoverable.Root>
  );
}

interface HookStatusPopoverProps {
  hook: HookResponse;
  spec: HookPointMeta | undefined;
  isBusy: boolean;
}

export default function HookStatusPopover({
  hook,
  spec,
  isBusy,
}: HookStatusPopoverProps) {
  const logsModal = useCreateModal();
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  // true = opened by click (stays until dismissed); false = opened by hover (closes after 1s)
  const [clickOpened, setClickOpened] = useState(false);
  const closeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const { hasRecentErrors, recentErrors, olderErrors, isLoading, error } =
    useHookExecutionLogs(hook.id);

  const topErrors = [...recentErrors, ...olderErrors]
    .sort(
      (a, b) =>
        new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
    )
    .slice(0, 3);

  useEffect(() => {
    return () => {
      if (closeTimerRef.current) clearTimeout(closeTimerRef.current);
    };
  }, []);

  useEffect(() => {
    if (error) {
      console.error(
        "HookStatusPopover: failed to fetch execution logs:",
        error
      );
    }
  }, [error]);

  function clearCloseTimer() {
    if (closeTimerRef.current) {
      clearTimeout(closeTimerRef.current);
      closeTimerRef.current = null;
    }
  }

  function scheduleClose() {
    clearCloseTimer();
    closeTimerRef.current = setTimeout(() => {
      setOpen(false);
      setClickOpened(false);
    }, 1000);
  }

  function handleTriggerMouseEnter() {
    clearCloseTimer();
    setOpen(true);
  }

  function handleTriggerMouseLeave() {
    if (!clickOpened) scheduleClose();
  }

  function handleTriggerClick() {
    clearCloseTimer();
    if (open && clickOpened) {
      // Click while click-opened → close
      setOpen(false);
      setClickOpened(false);
    } else {
      // Any click → open and pin
      setOpen(true);
      setClickOpened(true);
    }
  }

  function handleContentMouseEnter() {
    clearCloseTimer();
  }

  function handleContentMouseLeave() {
    if (!clickOpened) scheduleClose();
  }

  function handleOpenChange(newOpen: boolean) {
    if (!newOpen) {
      setOpen(false);
      setClickOpened(false);
      clearCloseTimer();
    }
  }

  return (
    <>
      <logsModal.Provider>
        <HookLogsModal hook={hook} spec={spec} />
      </logsModal.Provider>

      <Popover open={open} onOpenChange={handleOpenChange}>
        <Popover.Anchor asChild>
          <Button
            prominence="tertiary"
            rightIcon={({ className, ...props }) =>
              hook.is_reachable === false ? (
                <SvgXOctagon
                  {...props}
                  className={cn("text-status-error-05", className)}
                />
              ) : hasRecentErrors ? (
                <SvgAlertTriangle
                  {...props}
                  className={cn("text-status-warning-05", className)}
                />
              ) : (
                <SvgCheckCircle
                  {...props}
                  className={cn("text-status-success-05", className)}
                />
              )
            }
            onMouseEnter={handleTriggerMouseEnter}
            onMouseLeave={handleTriggerMouseLeave}
            onClick={noProp(handleTriggerClick)}
            disabled={isBusy}
          >
            {hook.is_reachable === false ? t("admin.hooks.status_connection_lost") : t("admin.hooks.status_connected")}
          </Button>
        </Popover.Anchor>

        <Popover.Content
          align="end"
          sideOffset={4}
          onMouseEnter={handleContentMouseEnter}
          onMouseLeave={handleContentMouseLeave}
        >
          <Section
            flexDirection="column"
            justifyContent="start"
            alignItems="start"
            height="fit"
            width={
              hook.is_reachable === false
                ? topErrors.length > 0
                  ? 20
                  : 12.5
                : hasRecentErrors
                  ? 20
                  : 12.5
            }
            padding={0.125}
            gap={0.25}
          >
            {isLoading ? (
              <Section justifyContent="center">
                <SvgSimpleLoader />
              </Section>
            ) : error ? (
              <Text font="secondary-body" color="text-03">
                {t("admin.hooks.status_failed_logs")}
              </Text>
            ) : hook.is_reachable === false ? (
              <>
                <div className="p-1">
                  <Content
                    sizePreset="secondary"
                    variant="section"
                    icon={(props) => (
                      <SvgXOctagon
                        {...props}
                        className="text-status-error-05"
                      />
                    )}
                    title={t("admin.hooks.status_most_recent_errors")}
                  />
                </div>

                {topErrors.length > 0 ? (
                  <>
                    <Divider paddingPerpendicular="fit" />

                    <Section
                      flexDirection="column"
                      justifyContent="start"
                      alignItems="start"
                      gap={0.25}
                      padding={0.25}
                      height="fit"
                    >
                      {topErrors.map((log, idx) => (
                        <ErrorLogRow
                          key={log.created_at + String(idx)}
                          log={log}
                          group={log.created_at + String(idx)}
                        />
                      ))}
                    </Section>
                  </>
                ) : (
                  <Divider paddingPerpendicular="fit" />
                )}

                <LineItem
                  muted
                  icon={SvgMaximize2}
                  onClick={noProp(() => {
                    handleOpenChange(false);
                    logsModal.toggle(true);
                  })}
                >
                  {t("admin.hooks.status_view_more")}
                </LineItem>
              </>
            ) : hasRecentErrors ? (
              <>
                <div className="p-1">
                  <Content
                    sizePreset="secondary"
                    variant="section"
                    icon={(props) => (
                      <SvgXOctagon
                        {...props}
                        className="text-status-error-05"
                      />
                    )}
                    title={
                      recentErrors.length <= 3
                        ? t("admin.hooks.status_error_count", { count: recentErrors.length })
                        : t("admin.hooks.status_most_recent_errors")
                    }
                    description={t("admin.hooks.status_in_past_hour")}
                  />
                </div>

                <Divider paddingPerpendicular="fit" />

                {/* Log rows — at most 3, timestamp first then error message */}
                <Section
                  flexDirection="column"
                  justifyContent="start"
                  alignItems="start"
                  gap={0.25}
                  padding={0.25}
                  height="fit"
                >
                  {recentErrors.slice(0, 3).map((log, idx) => (
                    <ErrorLogRow
                      key={log.created_at + String(idx)}
                      log={log}
                      group={log.created_at + String(idx)}
                    />
                  ))}
                </Section>

                {/* View More Lines */}
                <LineItem
                  muted
                  icon={SvgMaximize2}
                  onClick={noProp(() => {
                    handleOpenChange(false);
                    logsModal.toggle(true);
                  })}
                >
                  {t("admin.hooks.status_view_more")}
                </LineItem>
              </>
            ) : (
              // No errors state
              <>
                <div className="p-1">
                  <Content
                    sizePreset="secondary"
                    variant="section"
                    icon={SvgCheckCircle}
                    title={t("admin.hooks.status_no_error")}
                    description={t("admin.hooks.status_in_past_hour")}
                  />
                </div>

                <Divider paddingPerpendicular="fit" />

                {/* View Older Errors */}
                <LineItem
                  muted
                  icon={SvgMaximize2}
                  onClick={noProp(() => {
                    handleOpenChange(false);
                    logsModal.toggle(true);
                  })}
                >
                  {t("admin.hooks.status_view_older")}
                </LineItem>
              </>
            )}
          </Section>
        </Popover.Content>
      </Popover>
    </>
  );
}
