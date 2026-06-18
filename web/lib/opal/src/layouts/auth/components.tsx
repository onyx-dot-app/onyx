"use client";

import { Card as OpalCard, Text } from "@opal/components";
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
  return (
    <div className="flex min-h-screen items-center justify-center">
      {children}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Card — the auth card: logo + header + content + optional bottom prompt
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
    <div className="w-full max-w-(--auth-container-width)">
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
        <div className="mt-6 text-center">
          <Text color="text-03" as="p">
            {bottomPrompt}
          </Text>
        </div>
      )}
    </div>
  );
}

export { Root, Card };
export type { CardProps };
