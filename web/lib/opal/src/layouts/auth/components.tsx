"use client";

import "@opal/layouts/auth/styles.css";
import {
  Button,
  Card as OpalCard,
  EndOfList,
  MessageCard,
  Text,
} from "@opal/components";
import { Form } from "formik";
import SvgArrowRightCircle from "@opal/icons/arrow-right-circle";
import { Content } from "@opal/layouts";
import type { IconFunctionComponent, RichStr } from "@opal/types";
import { SvgSimpleLoader } from "@opal/icons";

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
  icon: IconFunctionComponent;
  title: string | RichStr;
  description?: string | RichStr;
  children?: React.ReactNode;
  bottomPrompt?: string | RichStr;
}

function Card({
  icon: Icon,
  title,
  description,
  children,
  bottomPrompt,
}: CardProps) {
  return (
    <div className="opal-auth-card-outer">
      <OpalCard padding="lg" rounding="lg" shadow="lg">
        <div className="flex flex-col gap-6">
          <div className="flex flex-col gap-3">
            <div className="p-0.5">
              <Icon size={48} />
            </div>
            <Content
              sizePreset="headline"
              variant="heading"
              title={title}
              description={description}
            />
          </div>
          <div className="flex flex-col gap-4">{children}</div>
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
// FormBody — Formik Form wrapper with standard auth-page layout classes
// ---------------------------------------------------------------------------

interface FormBodyProps {
  children: React.ReactNode;
}

function FormBody({ children }: FormBodyProps) {
  return (
    <Form className="w-full flex flex-col items-stretch gap-4">{children}</Form>
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

type SubmitLabel = "submit" | "create" | "join" | "reset" | "impersonate";

interface SubmitProps {
  label: SubmitLabel;
  isSubmitting?: boolean;
  isValid?: boolean;
  dirty?: boolean;
}

const SUBMIT_LABEL_TEXT: Record<SubmitLabel, string> = {
  submit: "Sign In",
  create: "Create Account",
  join: "Join",
  reset: "Reset Password",
  impersonate: "Impersonate",
};

function Submit({ label, isSubmitting, isValid, dirty }: SubmitProps) {
  return (
    <Button
      type="submit"
      width="full"
      disabled={
        Boolean(isSubmitting) ||
        (isValid !== undefined && !isValid) ||
        (dirty !== undefined && !dirty)
      }
      icon={isSubmitting ? SvgSimpleLoader : undefined}
      rightIcon={SvgArrowRightCircle}
    >
      {SUBMIT_LABEL_TEXT[label]}
    </Button>
  );
}

// ---------------------------------------------------------------------------
// Message — restrictive wrapper over MessageCard for auth pages
// ---------------------------------------------------------------------------

type MessageType = "default" | "warning" | "success";

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
    <MessageCard
      variant={messageType}
      title={title}
      description={description}
    />
  );
}

export {
  Root,
  type CardProps,
  Card,
  type FormBodyProps,
  FormBody,
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
