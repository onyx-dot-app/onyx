"use client";

import { useRouter } from "next/navigation";
import { cn } from "@opal/utils";
import { Divider, Button, Spacer } from "@opal/components";
import type {
  IconFunctionComponent,
  RichStr,
  SizeVariants,
  WithoutStyles,
} from "@opal/types";
import { HtmlHTMLAttributes, useEffect, useRef, useState } from "react";
import { Content } from "@opal/layouts";
import { SvgArrowLeft } from "@opal/icons";

// ---------------------------------------------------------------------------
// Root
// ---------------------------------------------------------------------------

const widthClasses: Record<
  Extract<SizeVariants, "sm" | "md" | "lg" | "full">,
  string
> = {
  sm: "w-[min(var(--app-container-sm),100%)]",
  md: "w-[min(var(--app-container-md),100%)]",
  lg: "w-[min(var(--app-container-lg),100%)]",
  full: "w-(--app-container-full)",
};

interface SettingsRootProps extends WithoutStyles<
  React.HtmlHTMLAttributes<HTMLDivElement>
> {
  width?: Extract<SizeVariants, "sm" | "md" | "lg" | "full">;
}

/**
 * Wrapper for settings pages. Creates a centered, scrollable container.
 * The `id="page-wrapper-scroll-container"` is referenced by `Header` for
 * scroll-shadow detection — do not remove it.
 */
function SettingsRoot({ width = "md", ...props }: SettingsRootProps) {
  return (
    <div
      id="page-wrapper-scroll-container"
      className="w-full h-full flex flex-col items-center overflow-y-auto"
    >
      <div className={cn("h-full", widthClasses[width])}>
        <div {...props} />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Header
// ---------------------------------------------------------------------------

export interface SettingsHeaderProps {
  icon: IconFunctionComponent;
  title: string | RichStr;
  description?: string | RichStr;
  children?: React.ReactNode;
  rightChildren?: React.ReactNode;
  backButton?: boolean | (() => void);
  divider?: boolean;
}

/**
 * Sticky header for settings pages. Shows a scroll shadow when the page
 * has scrolled. Headers with `rightChildren` are always sticky; others are not.
 *
 * Back button: set `backButton` to show a "← Back" button. Supply a function
 * to override the default `router.back()` behavior.
 */
function SettingsHeader({
  icon: Icon,
  title,
  description,
  children,
  rightChildren,
  backButton,
  divider,
}: SettingsHeaderProps) {
  const router = useRouter();
  const [showShadow, setShowShadow] = useState(false);
  const headerRef = useRef<HTMLDivElement>(null);

  const isSticky = !!rightChildren;
  const showBackButton = !!backButton;
  const onBack =
    typeof backButton === "function" ? backButton : () => router.back();

  useEffect(() => {
    if (!isSticky) return;

    const scrollContainer = document.getElementById(
      "page-wrapper-scroll-container"
    );
    if (!scrollContainer) return;

    const handleScroll = () => {
      setShowShadow(scrollContainer.scrollTop > 0);
    };

    scrollContainer.addEventListener("scroll", handleScroll);
    handleScroll();

    return () => scrollContainer.removeEventListener("scroll", handleScroll);
  }, [isSticky]);

  return (
    <div
      ref={headerRef}
      className={cn(
        "w-full",
        isSticky && "sticky top-0 z-settings-header bg-background-tint-01",
        showBackButton && "md:pt-4"
      )}
    >
      {showBackButton && (
        <div className="px-2">
          <Button icon={SvgArrowLeft} prominence="tertiary" onClick={onBack}>
            Back
          </Button>
        </div>
      )}

      <Spacer rem={3.25} />

      <div className="flex flex-col gap-6 px-4">
        <div className="flex w-full justify-between">
          <div aria-label="admin-page-title">
            <Content
              icon={Icon}
              title={title}
              description={description}
              sizePreset="headline"
              variant="heading"
            />
          </div>
          {rightChildren}
        </div>

        {children}
      </div>

      {divider ? (
        <>
          <Spacer rem={1.5} />
          <Divider paddingParallel="md" paddingPerpendicular="fit" />
        </>
      ) : (
        <Spacer rem={0.5} />
      )}

      {isSticky && (
        <div
          className={cn(
            "absolute left-0 right-0 h-2 pointer-events-none transition-opacity duration-300 rounded-b-08 opacity-0",
            showShadow && "opacity-100"
          )}
          style={{
            background:
              "linear-gradient(to bottom, var(--mask-02), transparent)",
          }}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Body
// ---------------------------------------------------------------------------

function SettingsBody(
  props: WithoutStyles<HtmlHTMLAttributes<HTMLDivElement>>
) {
  return (
    <div className="pt-6 pb-18 px-4 flex flex-col gap-8 w-full" {...props} />
  );
}

// ---------------------------------------------------------------------------
// Exports
// ---------------------------------------------------------------------------

export { SettingsRoot as Root, SettingsHeader as Header, SettingsBody as Body };
