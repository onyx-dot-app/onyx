"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import {
  Button,
  CopyButton,
  Divider,
  LineItemButton,
  Popover,
  Text,
  useCreateModal,
} from "@opal/components";
import { noProp } from "@/lib/utils";
import { formatDateTimeLog } from "@/lib/dateUtils";
import { Content } from "@opal/layouts";
import { Section } from "@/layouts/general-layouts";
import {
  SvgAlertTriangle,
  SvgCheckCircle,
  SvgMaximize2,
  SvgXOctagon,
  SvgSimpleLoader,
} from "@opal/icons";
import { Hoverable } from "@opal/core";
import { useHookExecutionLogs } from "@/ee/hooks/useHookExecutionLogs";
import HookLogsModal from "@/ee/views/admin/HooksPage/HookLogsModal";
import type {
  HookPointMeta,
  HookResponse,
} from "@/ee/views/admin/HooksPage/interfaces";
import { cn } from "@opal/utils";

function ErrorLogRow({
  log,
  group,
}: {
  log: { created_at: string; error_message: string | null };
  group: string;
}) {
  const t = useTranslations("admin.hooks");
  return (
    <Hoverable.Root group={group}>
      <Section
        flexDirection="column"
        justifyContent="start"
        alignItems="start"
        gap={1}
        padding={1}
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
            {log.error_message ?? t("logs.unknownError.label")}
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
  const t = useTranslations("admin.hooks");
  const logsModal = useCreateModal();
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
            {hook.is_reachable === false
              ? t("status.connectionLost.label")
              : t("status.connected.label")}
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
            padding={0.5}
            gap={1}
          >
            {isLoading ? (
              <Section justifyContent="center">
                <SvgSimpleLoader />
              </Section>
            ) : error ? (
              <Text font="secondary-body" color="text-03">
                {t("logs.loadFailed.message")}
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
                    title={t("status.recentErrors.title")}
                  />
                </div>

                {topErrors.length > 0 ? (
                  <>
                    <Divider paddingPerpendicular={0} />

                    <Section
                      flexDirection="column"
                      justifyContent="start"
                      alignItems="start"
                      gap={1}
                      padding={1}
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
                  <Divider paddingPerpendicular={0} />
                )}

                <LineItemButton
                  sizePreset="main-ui"
                  rounding={2}
                  color="muted"
                  icon={SvgMaximize2}
                  onClick={noProp(() => {
                    handleOpenChange(false);
                    logsModal.toggle(true);
                  })}
                  title={t("status.viewMore.label")}
                />
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
                        ? t("status.errorCount.title", {
                            count: recentErrors.length,
                          })
                        : t("status.recentErrors.title")
                    }
                    description={t("status.pastHour.description")}
                  />
                </div>

                <Divider paddingPerpendicular={0} />

                {/* Log rows — at most 3, timestamp first then error message */}
                <Section
                  flexDirection="column"
                  justifyContent="start"
                  alignItems="start"
                  gap={1}
                  padding={1}
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
                <LineItemButton
                  sizePreset="main-ui"
                  rounding={2}
                  color="muted"
                  icon={SvgMaximize2}
                  onClick={noProp(() => {
                    handleOpenChange(false);
                    logsModal.toggle(true);
                  })}
                  title={t("status.viewMore.label")}
                />
              </>
            ) : (
              // No errors state
              <>
                <div className="p-1">
                  <Content
                    sizePreset="secondary"
                    variant="section"
                    icon={SvgCheckCircle}
                    title={t("status.noError.title")}
                    description={t("status.pastHour.description")}
                  />
                </div>

                <Divider paddingPerpendicular={0} />

                {/* View Older Errors */}
                <LineItemButton
                  sizePreset="main-ui"
                  rounding={2}
                  color="muted"
                  icon={SvgMaximize2}
                  onClick={noProp(() => {
                    handleOpenChange(false);
                    logsModal.toggle(true);
                  })}
                  title={t("status.viewOlder.label")}
                />
              </>
            )}
          </Section>
        </Popover.Content>
      </Popover>
    </>
  );
}
