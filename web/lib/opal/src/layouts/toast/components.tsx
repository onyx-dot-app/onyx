"use client";

import "@opal/layouts/toast/styles.css";
import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import { cn } from "@opal/utils";
import { Button, MessageCard, Badge, Text } from "@opal/components";
import { SvgX } from "@opal/icons";
import type { IconProps } from "@opal/types";
import { useOpalStrings } from "@opal/strings";
import useOverflow from "@opal/hooks/useOverflow";
import useScreenSize from "@opal/hooks/useScreenSize";
import {
  shownToasts,
  toast,
  toastStore,
  type Toast,
} from "@opal/layouts/toast/store";
import SvgChevronRight from "@opal/icons/chevron-right";
import { Section } from "@opal/layouts/general/components";

// How long a toast lingers after the user expands it. Long enough to read a
// multi-line stack trace or API error without forcing a manual dismiss.
// Piled layers that peek out as edges; deeper ones are out of sight.
const MAX_PILE_DEPTH_SHOWN = 2;
const EXPANDED_DURATION_MS = 30000;

function buildDescription(
  t: Toast,
  errorAppendix?: string
): string | undefined {
  const parts: string[] = [];
  if (t.description) parts.push(t.description);
  if (t.level === "error" && errorAppendix) parts.push(errorAppendix);
  return parts.length > 0 ? parts.join(" ") : undefined;
}

interface ExpandedDetailsProps {
  message: string;
}

function ExpandedDetails({ message }: ExpandedDetailsProps) {
  return (
    <div
      // oxlint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- Keyboard users can scroll the full message.
      tabIndex={0}
      className="max-h-[min(18rem,25dvh)] overflow-y-auto whitespace-pre-wrap px-3 py-2 wrap-break-word"
    >
      <Text font="secondary-body" color="text-03" as="p">
        {message}
      </Text>
    </div>
  );
}

/**
 * The expand toggle's chevron. A stable component, so the SVG persists and
 * its rotation can transition; it turns with the button's `aria-expanded`.
 */
function ToastChevronIcon({ className, ...props }: IconProps) {
  return (
    <SvgChevronRight
      {...props}
      className={cn(className, "opal-toast-chevron")}
    />
  );
}

interface ToastCardProps {
  toast: Toast;
  /**
   * Its layer in the pile below the stack: 1 and 2 peek out as edges behind
   * the toast above, deeper ones are hidden. Undefined while on show.
   */
  pileDepth?: number;
  /** Its z-index: its place in the stack, top highest. */
  layer: number;
  errorAppendix?: string;
  expanded: boolean;
  onToggle: (t: Toast) => void;
  onClose: (id: string) => void;
}

/**
 * On narrow screens, plain titles use two lines and controls sit below the message.
 * Wider screens keep a one-line title with an expansion control.
 */
function ToastCard({
  toast: t,
  pileDepth,
  layer,
  errorAppendix,
  expanded,
  onToggle,
  onClose,
}: ToastCardProps) {
  const strings = useOpalStrings();
  const { isMobile } = useScreenSize();
  // The title lives inside MessageCard; ContentMd marks it so it can be
  // measured from here.
  const [title, setTitle] = useState<HTMLElement | null>(null);
  const ref = useCallback((node: HTMLDivElement | null) => {
    setTitle(
      node?.querySelector<HTMLElement>("[data-opal-content-title]") ?? null
    );
  }, []);
  const titleOverflows = useOverflow(title);
  const truncated = !t.children && titleOverflows;
  const close = t.dismissible ? () => onClose(t.id) : undefined;
  const action = t.action;
  const shared = {
    innerPadding: 1,
    variant: t.level ?? "info",
    title: t.message,
    titleMaxLines: t.children ? undefined : isMobile ? 2 : 1,
    description: buildDescription(t, errorAppendix),
    outerPadding: 1,
    contentPadding: 1,
  } as const;
  const controls = (
    <Section flexDirection="row" justifyContent="end" height="auto" gap={0}>
      {action && (
        <Button
          icon={action.icon}
          prominence="internal"
          size="md"
          tooltip={action.label}
          aria-label={action.label}
          onClick={action.onClick}
        />
      )}
      {truncated && (
        <Button
          icon={ToastChevronIcon}
          prominence="internal"
          size="md"
          onClick={() => onToggle(t)}
          aria-label={strings.showFullMessage}
          aria-expanded={expanded}
        />
      )}
      {close && (
        <Button
          icon={SvgX}
          prominence="internal"
          size="md"
          onClick={close}
          aria-label={strings.close}
        />
      )}
    </Section>
  );

  return (
    <div
      ref={ref}
      className="opal-toast"
      data-leaving={t.leaving || undefined}
      data-pile={
        pileDepth === undefined
          ? undefined
          : pileDepth > MAX_PILE_DEPTH_SHOWN
            ? "deep"
            : pileDepth
      }
      inert={pileDepth !== undefined}
      style={{ zIndex: layer }}
    >
      <div
        className="opal-toast-body"
        role={t.children ? undefined : t.level === "error" ? "alert" : "status"}
        aria-atomic={t.children ? undefined : true}
      >
        <div className="opal-toast-spacer">
          {isMobile ? (
            <MessageCard
              {...shared}
              bottomChildren={
                t.children || truncated || action || close ? (
                  <>
                    {truncated && expanded && (
                      <ExpandedDetails message={t.message} />
                    )}
                    {t.children}
                    {controls}
                  </>
                ) : undefined
              }
            />
          ) : truncated || action ? (
            <MessageCard
              {...shared}
              rightChildren={controls}
              bottomChildren={
                truncated && expanded ? (
                  <>
                    <ExpandedDetails message={t.message} />
                    {t.children}
                  </>
                ) : (
                  t.children
                )
              }
            />
          ) : (
            <MessageCard
              {...shared}
              onClose={close}
              bottomChildren={t.children}
            />
          )}
        </div>
      </div>
    </div>
  );
}

interface ToastContainerProps {
  errorAppendix?: string;
}

function ToastContainer({ errorAppendix }: ToastContainerProps) {
  const allToasts = useSyncExternalStore(
    toastStore.subscribe,
    toastStore.getSnapshot,
    toastStore.getSnapshot
  );
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());

  const strings = useOpalStrings();
  // Newest first. The toasts holding the stack's slots are on show; older
  // ones pile below. A leaving toast holds its slot until its space starts to
  // close, so the next one rises out of the pile as the stack moves up.
  const shownIds = new Set(shownToasts(allToasts).map((t) => t.id));
  // A leaving toast keeps the place it left from until it is gone: one that
  // slid off a slot never joins the pile, so the pile's layers hold still.
  const piled = allToasts.filter((t) => !t.leaving && !shownIds.has(t.id));
  const pileCount = piled.length;
  // Each piled toast's layer, newest first: the newest piled toast sits just
  // behind the stack.
  const pileDepths = new Map(
    [...piled].reverse().map((t, index) => [t.id, index + 1])
  );
  const DEEP = MAX_PILE_DEPTH_SHOWN + 1;

  // A gone toast leaves no expanded state behind for a later one with its id.
  useEffect(() => {
    setExpandedIds((prev) => {
      const live = new Set(allToasts.map((t) => t.id));
      const next = new Set([...prev].filter((id) => live.has(id)));
      return next.size === prev.size ? prev : next;
    });
  }, [allToasts]);

  const handleClose = useCallback((id: string) => {
    toast.dismiss(id);
  }, []);

  const handleToggle = useCallback((t: Toast) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(t.id)) next.delete(t.id);
      else next.add(t.id);
      return next;
    });
    // Restart auto-dismiss with reading time for the full message. Persistent
    // toasts stay persistent.
    if (t.duration !== Infinity) {
      toast.setAutoDismiss(t.id, EXPANDED_DURATION_MS);
    }
  }, []);
  if (allToasts.length === 0) return null;

  return (
    <div
      data-testid="toast-container"
      className="opal-toast-viewport fixed inset-x-4 top-2 z-(--z-toast) mx-auto flex max-w-(--toast-width) flex-col items-center"
    >
      <div className="opal-toast-stack">
        {[...allToasts].reverse().map((t, index) => (
          <ToastCard
            key={t.id}
            toast={t}
            // Layered by place, top highest: piling and rising never change
            // the order, so a card stays behind the one above it throughout.
            layer={allToasts.length - index}
            pileDepth={
              t.leaving
                ? t.leavingFromPile
                  ? DEEP
                  : undefined
                : pileDepths.get(t.id)
            }
            errorAppendix={errorAppendix}
            expanded={expandedIds.has(t.id)}
            onToggle={handleToggle}
            onClose={handleClose}
          />
        ))}
      </div>
      {/* A count, not a control: the pile does not expand (see the README's
          design decisions). */}
      {pileCount > 0 && (
        <div className="opal-toast-pile-count">
          <Badge
            title={strings.toastMoreCount(pileCount)}
            color="default"
            size={6}
          />
        </div>
      )}
    </div>
  );
}

interface ToastProviderProps {
  children: React.ReactNode;

  /** Appended to every error toast's description (e.g. a support link). */
  errorAppendix?: string;
}

/**
 * Renders the app's toast stack top-centre, 0.5rem from the top, driven by the module-level
 * store in `toast/store` (fire toasts from anywhere via `toast(...)` or the
 * `useToast` hook). A title that overflows its one line gets a chevron that
 * shows and hides the full message.
 */
function ToastProvider({ children, errorAppendix }: ToastProviderProps) {
  return (
    <>
      {children}
      <ToastContainer errorAppendix={errorAppendix} />
    </>
  );
}

export { ToastProvider, type ToastProviderProps };
