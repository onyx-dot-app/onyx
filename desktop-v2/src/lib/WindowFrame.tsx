import { useLayoutEffect, useRef, type ReactNode } from "react";
import { getCurrentWindow, LogicalSize } from "@tauri-apps/api/window";
import { Text } from "@opal/components";
import { Section } from "@opal/layouts";

interface WindowFrameProps {
  title: string;
  subtitle?: string;
  children: ReactNode;
}

// Height of the title-bar row above the content.
const TITLE_BAR = 24;

// Shared layout for the small native windows (onboarding, login, preferences).
// The window is as tall as its content.
export function WindowFrame({ title, subtitle, children }: WindowFrameProps) {
  const contentRef = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    const content = contentRef.current;
    if (!content) return;
    const fit = () => {
      // Content taller than the screen scrolls instead.
      const height = Math.min(content.offsetHeight + TITLE_BAR, window.screen.availHeight - 80);
      void getCurrentWindow().setSize(new LogicalSize(window.innerWidth, height));
    };
    fit();
    const observer = new ResizeObserver(fit);
    observer.observe(content);
    return () => observer.disconnect();
  }, []);

  return (
    <Section gap={0} justifyContent="start" alignItems="stretch">
      <div className="drag-region h-6 shrink-0" data-tauri-drag-region />
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div ref={contentRef}>
        <Section gap={6} padding={8} justifyContent="start" alignItems="stretch" height="fit">
          <Section flexDirection="row" gap={3} justifyContent="start" height="fit">
            <img src="/onyx-logo.svg" alt="" className="h-8 w-8" />
            <Section gap={0} alignItems="start" height="fit">
              <Text font="heading-section" color="text-05">
                {title}
              </Text>
              {subtitle ? (
                <Text font="secondary-body" color="text-03">
                  {subtitle}
                </Text>
              ) : null}
            </Section>
          </Section>
          {children}
        </Section>
        </div>
      </div>
    </Section>
  );
}

interface FieldProps {
  label: string;
  // The id of the input this label names, for assistive technology.
  inputId: string;
  children: ReactNode;
}

export function Field({ label, inputId, children }: FieldProps) {
  return (
    <Section gap={1.5} alignItems="stretch" height="fit">
      <label htmlFor={inputId}>
        <Text font="secondary-action" color="text-04">
          {label}
        </Text>
      </label>
      {children}
    </Section>
  );
}

interface ErrorTextProps {
  message: string | null;
}

export function ErrorText({ message }: ErrorTextProps) {
  if (!message) return null;
  return (
    <p role="alert" className="font-secondary-body text-status-error-05">
      {message}
    </p>
  );
}
