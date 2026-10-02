"use client";

import "@opal/layouts/toast/styles.css";
import { useCallback, useState, useSyncExternalStore } from "react";
import { cn } from "@opal/utils";
import { Button, MessageCard, Text } from "@opal/components";
import { SvgX } from "@opal/icons";
import type { IconProps } from "@opal/types";
import { useOpalStrings } from "@opal/strings";
import useOverflow from "@opal/hooks/useOverflow";
import {
  MAX_VISIBLE_TOASTS,
  toast,
  toastStore,
  type Toast,
} from "@opal/layouts/toast/store";
import SvgChevronRight from "@opal/icons/chevron-right";
import { Section } from "../general/components";

const ANIMATION_DURATION = 200; // matches tailwind fade-out-scale (0.2s)
// How long a toast lingers after the user expands it. Long enough to read a
// multi-line stack trace or API error without forcing a manual dismiss.
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
    <div className="max-h-72 overflow-y-auto whitespace-pre-wrap px-3 py-2 wrap-break-word">
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
  errorAppendix?: string;
  expanded: boolean;
  onToggle: (t: Toast) => void;
  onClose: (id: string) => void;
}

/**
 * One toast. The title stays on one line; when that line cuts it off, a
 * chevron left of the close button shows and hides the full message below.
 */
function ToastCard({
  toast: t,
  errorAppendix,
  expanded,
  onToggle,
  onClose,
}: ToastCardProps) {
  const strings = useOpalStrings();
  // The title lives inside MessageCard; ContentMd marks it so it can be
  // measured from here.
  const [title, setTitle] = useState<HTMLElement | null>(null);
  const ref = useCallback((node: HTMLDivElement | null) => {
    setTitle(
      node?.querySelector<HTMLElement>("[data-opal-content-title]") ?? null
    );
  }, []);
  const truncated = useOverflow(title);
  const close = t.dismissible ? () => onClose(t.id) : undefined;
  const shared = {
    innerPadding: 1,
    variant: t.level ?? "info",
    title: t.message,
    titleMaxLines: 1,
    description: buildDescription(t, errorAppendix),
    outerPadding: 1,
    contentPadding: 1,
  } as const;

  return (
    <div ref={ref} className="opal-toast" data-leaving={t.leaving || undefined}>
      <div className="opal-toast-body">
        {truncated ? (
          <MessageCard
            {...shared}
            rightChildren={
              <Section flexDirection="row" gap={0}>
                <Button
                  icon={ToastChevronIcon}
                  prominence="internal"
                  size="md"
                  onClick={() => onToggle(t)}
                  aria-label={strings.showFullMessage}
                  aria-expanded={expanded}
                />
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
            }
            bottomChildren={
              expanded ? <ExpandedDetails message={t.message} /> : undefined
            }
          />
        ) : (
          <MessageCard {...shared} onClose={close} />
        )}
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

  // The newest toasts that are not leaving, plus any still leaving in place.
  // A closed toast stops counting as it starts to leave, so the next hidden
  // one slides in while it slides out.
  const shownIds = new Set(
    allToasts
      .filter((t) => !t.leaving)
      .slice(-MAX_VISIBLE_TOASTS)
      .map((t) => t.id)
  );
  const visible = allToasts.filter((t) => t.leaving || shownIds.has(t.id));

  const handleClose = useCallback((id: string) => {
    toast._markLeaving(id);
    setTimeout(() => {
      toast.dismiss(id);
      setExpandedIds((prev) => {
        if (!prev.has(id)) return prev;
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    }, ANIMATION_DURATION);
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
  if (visible.length === 0) return null;

  return (
    <div
      data-testid="toast-container"
      className="fixed inset-x-4 top-2 z-(--z-toast) mx-auto flex max-w-(--toast-width) flex-col items-center"
    >
      {visible.map((t) => (
        <ToastCard
          key={t.id}
          toast={t}
          errorAppendix={errorAppendix}
          expanded={expandedIds.has(t.id)}
          onToggle={handleToggle}
          onClose={handleClose}
        />
      ))}
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
