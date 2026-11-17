import type { ReactNode } from "react";
import { Text } from "@opal/components";
import { Section } from "@opal/layouts";

interface WindowFrameProps {
  title: string;
  subtitle?: string;
  children: ReactNode;
}

// Shared layout for the small native windows (onboarding, login, preferences).
export function WindowFrame({ title, subtitle, children }: WindowFrameProps) {
  return (
    <Section gap={0} justifyContent="start" alignItems="stretch">
      <div className="drag-region h-6 shrink-0" data-tauri-drag-region />
      {/* The windows have a fixed size: content that does not fit scrolls. */}
      <div className="min-h-0 flex-1 overflow-y-auto">
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
