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
      <Section gap={6} padding={8} justifyContent="start" alignItems="stretch">
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
    </Section>
  );
}

interface FieldProps {
  label: string;
  children: ReactNode;
}

export function Field({ label, children }: FieldProps) {
  return (
    <Section gap={1.5} alignItems="stretch" height="fit">
      <Text font="secondary-action" color="text-04">
        {label}
      </Text>
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
