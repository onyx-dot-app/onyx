"use client";

import "@opal/layouts/auth/styles.css";
import {
  Button,
  Card as OpalCard,
  EndOfList,
  MessageCard,
  Text,
} from "@opal/components";
import SvgArrowRightCircle from "@opal/icons/arrow-right-circle";
import { Content } from "@opal/layouts";
import { SvgOnyxLogo } from "@opal/logos";
import type { RichStr } from "@opal/types";

// ---------------------------------------------------------------------------
// Root — screen-centering wrapper for auth pages
// ---------------------------------------------------------------------------

interface RootProps {
  children: React.ReactNode;
}

function Root({ children }: RootProps) {
  return <div className="opal-auth-root">{children}</div>;
}

// ---------------------------------------------------------------------------
// Card — logo + header + content + optional bottom prompt
// ---------------------------------------------------------------------------

interface CardProps {
  title: string | RichStr;
  description?: string | RichStr;
  children?: React.ReactNode;
  bottomPrompt?: string | RichStr;
  logoSrc?: string | null;
}

function Card({
  title,
  description,
  children,
  bottomPrompt,
  logoSrc,
}: CardProps) {
  return (
    <div className="opal-auth-card-outer">
      <OpalCard padding="lg" rounding="lg">
        <div className="flex flex-col gap-6">
          <div className="flex flex-col gap-3">
            <div className="p-0.5">
              {logoSrc ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  alt="Logo"
                  src={logoSrc}
                  className="rounded-full object-cover object-center"
                  style={{ width: "3rem", height: "3rem" }}
                />
              ) : (
                <SvgOnyxLogo size={48} />
              )}
            </div>
            <Content
              sizePreset="headline"
              variant="heading"
              title={title}
              description={description}
            />
          </div>
          {children}
        </div>
      </OpalCard>

      {bottomPrompt && (
        <div className="opal-auth-card-bottom-prompt">
          <Text color="text-03" as="p">
            {bottomPrompt}
          </Text>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// OrSeparator — "or" label flanked by two divider lines
// ---------------------------------------------------------------------------

function OrSeparator() {
  return <EndOfList title="or" />;
}

// ---------------------------------------------------------------------------
// Fields — consistent-gap container for form inputs
// ---------------------------------------------------------------------------

interface FieldsProps {
  children: React.ReactNode;
}

function Fields({ children }: FieldsProps) {
  return <div className="opal-auth-fields">{children}</div>;
}

// ---------------------------------------------------------------------------
// Submit — full-width submit button
// ---------------------------------------------------------------------------

type SubmitLabel = "submit" | "create" | "join" | "reset";

interface SubmitProps {
  label: SubmitLabel;
  disabled?: boolean;
}

const SUBMIT_LABEL_TEXT: Record<SubmitLabel, string> = {
  submit: "Submit",
  create: "Create",
  join: "Join",
  reset: "Reset Password",
};

function Submit({ label, disabled }: SubmitProps) {
  return (
    <Button
      type="submit"
      width="full"
      disabled={disabled}
      rightIcon={SvgArrowRightCircle}
    >
      {SUBMIT_LABEL_TEXT[label]}
    </Button>
  );
}

// ---------------------------------------------------------------------------
// Message — restrictive wrapper over MessageCard for auth pages
// ---------------------------------------------------------------------------

type MessageType = "default" | "warning";

interface MessageProps {
  messageType?: MessageType;
  title: string | RichStr;
  description: string | RichStr;
}

function Message({
  messageType = "default",
  title,
  description,
}: MessageProps) {
  return (
    <div className="pt-2">
      <MessageCard
        variant={messageType}
        title={title}
        description={description}
      />
    </div>
  );
}

export {
  Root,
  type CardProps,
  Card,
  OrSeparator,
  type FieldsProps,
  Fields,
  type SubmitLabel,
  type SubmitProps,
  Submit,
  type MessageType,
  type MessageProps,
  Message,
};
