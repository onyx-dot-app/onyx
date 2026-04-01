"use client";

import { useEffect, useRef, useState } from "react";
import { useCreateModal } from "@/refresh-components/contexts/ModalContext";
import { cn } from "@/lib/utils";
import { formatTimeOnly } from "@/lib/dateUtils";
import { Text } from "@opal/components";
import LineItem from "@/refresh-components/buttons/LineItem";
import Popover from "@/refresh-components/Popover";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import Separator from "@/refresh-components/Separator";
import { Section } from "@/layouts/general-layouts";
import {
  SvgAlertTriangle,
  SvgCheckCircle,
  SvgMaximize2,
  SvgXOctagon,
} from "@opal/icons";
import CopyIconButton from "@/refresh-components/buttons/CopyIconButton";
import { useHookExecutionLogs } from "@/ee/hooks/useHookExecutionLogs";
import HookLogsModal from "@/ee/refresh-pages/admin/HooksPage/HookLogsModal";
import type {
  HookPointMeta,
  HookResponse,
} from "@/ee/refresh-pages/admin/HooksPage/interfaces";

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
  const [open, setOpen] = useState(false);
  // true = opened by click (stays until dismissed); false = opened by hover (closes after 1s)
  const [clickOpened, setClickOpened] = useState(false);
  const closeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const { hasRecentErrors, recentErrors, isLoading, error } =
    useHookExecutionLogs(hook.id);

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
        <HookLogsModal
          open
          onOpenChange={(v) => !v && logsModal.toggle(false)}
          hook={hook}
          spec={spec}
        />
      </logsModal.Provider>

      <Popover open={open} onOpenChange={handleOpenChange}>
        <Popover.Anchor asChild>
          <div
            onMouseEnter={handleTriggerMouseEnter}
            onMouseLeave={handleTriggerMouseLeave}
            onClick={handleTriggerClick}
            className={cn(
              "flex items-center gap-1 cursor-pointer rounded-xl p-2 transition-colors hover:bg-background-neutral-02",
              isBusy && "opacity-50 pointer-events-none"
            )}
          >
            <Text font="main-ui-action" color="text-03">
              Connected
            </Text>
            {hasRecentErrors ? (
              <SvgAlertTriangle
                size={16}
                className="text-status-warning-05 shrink-0"
              />
            ) : (
              <SvgCheckCircle
                size={16}
                className="text-status-success-05 shrink-0"
              />
            )}
          </div>
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
            width={hasRecentErrors ? 20 : 12.5}
          >
            {isLoading ? (
              <Section justifyContent="center" height="fit" className="p-3">
                <SimpleLoader />
              </Section>
            ) : error ? (
              <Section justifyContent="center" height="fit" className="p-3">
                <Text font="secondary-body" color="text-03">
                  Failed to load logs.
                </Text>
              </Section>
            ) : hasRecentErrors ? (
              // Errors state
              <>
                {/* Header: "N Errors" (≤3) or "Most Recent Errors" (>3) */}
                <Section
                  flexDirection="row"
                  justifyContent="start"
                  alignItems="start"
                  gap={0.25}
                  padding={0.375}
                  height="fit"
                  className="rounded-lg"
                >
                  <Section
                    justifyContent="center"
                    alignItems="center"
                    width={1.25}
                    height={1.25}
                    className="shrink-0"
                  >
                    <SvgXOctagon size={16} className="text-status-error-05" />
                  </Section>
                  <Section
                    flexDirection="column"
                    justifyContent="start"
                    alignItems="start"
                    width="fit"
                    height="fit"
                    gap={0}
                    className="px-0.5"
                  >
                    <Text font="main-ui-action" color="text-04">
                      {recentErrors.length <= 3
                        ? `${recentErrors.length} ${
                            recentErrors.length === 1 ? "Error" : "Errors"
                          }`
                        : "Most Recent Errors"}
                    </Text>
                    <Text font="secondary-body" color="text-03">
                      in the past hour
                    </Text>
                  </Section>
                </Section>

                <Separator noPadding className="py-1" />

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
                    <Section
                      key={log.created_at + String(idx)}
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
                            {formatTimeOnly(log.created_at)}
                          </Text>
                        </span>
                        <CopyIconButton
                          size="xs"
                          getCopyText={() => log.error_message ?? ""}
                        />
                      </Section>
                      <span className="break-all">
                        <Text font="secondary-mono" color="text-03">
                          {log.error_message ?? "Unknown error"}
                        </Text>
                      </span>
                    </Section>
                  ))}
                </Section>

                {/* View More Lines */}
                <LineItem
                  muted
                  icon={SvgMaximize2}
                  onClick={() => {
                    handleOpenChange(false);
                    logsModal.toggle(true);
                  }}
                >
                  View More Lines
                </LineItem>
              </>
            ) : (
              // No errors state
              <>
                {/* No Error / in the past hour */}
                <Section
                  flexDirection="row"
                  justifyContent="start"
                  alignItems="start"
                  gap={0.25}
                  padding={0.375}
                  height="fit"
                  className="rounded-lg"
                >
                  <Section
                    justifyContent="center"
                    alignItems="center"
                    width={1.25}
                    height={1.25}
                    className="shrink-0"
                  >
                    <SvgCheckCircle
                      size={16}
                      className="text-status-success-05"
                    />
                  </Section>
                  <Section
                    flexDirection="column"
                    justifyContent="start"
                    alignItems="start"
                    width="fit"
                    height="fit"
                    gap={0}
                    className="px-0.5"
                  >
                    <Text font="main-ui-action" color="text-04">
                      No Error
                    </Text>
                    <Text font="secondary-body" color="text-03">
                      in the past hour
                    </Text>
                  </Section>
                </Section>

                <Separator noPadding className="py-1" />

                {/* View Older Errors */}
                <LineItem
                  muted
                  icon={SvgMaximize2}
                  onClick={() => {
                    handleOpenChange(false);
                    logsModal.toggle(true);
                  }}
                >
                  View Older Errors
                </LineItem>
              </>
            )}
          </Section>
        </Popover.Content>
      </Popover>
    </>
  );
}
