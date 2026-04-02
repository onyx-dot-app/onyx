"use client";

import { useEffect, useRef, useState } from "react";
import { useCreateModal } from "@/refresh-components/contexts/ModalContext";
import { noProp } from "@/lib/utils";
import { formatTimeOnly } from "@/lib/dateUtils";
import { Button, Text } from "@opal/components";
import { Content } from "@opal/layouts";
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
import { cn } from "@opal/utils";

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
        <HookLogsModal hook={hook} spec={spec} />
      </logsModal.Provider>

      <Popover open={open} onOpenChange={handleOpenChange}>
        <Popover.Anchor asChild>
          <Button
            prominence="tertiary"
            rightIcon={({ className, ...props }) =>
              hasRecentErrors ? (
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
            Connected
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
            width={hasRecentErrors ? 20 : 12.5}
            padding={0.125}
            gap={0.25}
          >
            {isLoading ? (
              <Section justifyContent="center">
                <SimpleLoader />
              </Section>
            ) : error ? (
              <Text font="secondary-body" color="text-03">
                Failed to load logs.
              </Text>
            ) : hasRecentErrors ? (
              <>
                <div className="p-1">
                  <Content
                    sizePreset="secondary"
                    variant="section"
                    icon={SvgXOctagon}
                    title={
                      recentErrors.length <= 3
                        ? `${recentErrors.length} ${
                            recentErrors.length === 1 ? "Error" : "Errors"
                          }`
                        : "Most Recent Errors"
                    }
                    description="in the past hour"
                  />
                </div>

                <Separator noPadding className="px-2" />

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
                  onClick={noProp(() => {
                    handleOpenChange(false);
                    logsModal.toggle(true);
                  })}
                >
                  View More Lines
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
                    title="No Error"
                    description="in the past hour"
                  />
                </div>

                <Separator noPadding className="px-2" />

                {/* View Older Errors */}
                <LineItem
                  muted
                  icon={SvgMaximize2}
                  onClick={noProp(() => {
                    handleOpenChange(false);
                    logsModal.toggle(true);
                  })}
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
