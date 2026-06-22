"use client";

import "@opal/layouts/auth/styles.css";
import {
  Button,
  Card as OpalCard,
  EndOfList,
  Text,
  type ButtonProps,
} from "@opal/components";
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
// FormFields — consistent-gap container for form inputs
// ---------------------------------------------------------------------------

interface FormFieldsProps {
  children: React.ReactNode;
}

function FormFields({ children }: FormFieldsProps) {
  return <div className="opal-auth-form-fields">{children}</div>;
}

// ---------------------------------------------------------------------------
// Submit — full-width submit button
// ---------------------------------------------------------------------------

interface SubmitProps {
  children: string;
  disabled?: boolean;
  rightIcon?: ButtonProps["rightIcon"];
}

function Submit({ children, disabled, rightIcon }: SubmitProps) {
  return (
    <Button
      type="submit"
      width="full"
      disabled={disabled}
      rightIcon={rightIcon}
    >
      {children}
    </Button>
  );
}

export { Root, Card, OrSeparator, FormFields, Submit };
export type { CardProps, FormFieldsProps, SubmitProps };
