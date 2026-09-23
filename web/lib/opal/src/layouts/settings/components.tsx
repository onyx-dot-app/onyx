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
import { useOpalStrings } from "@opal/strings";

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
  /** Extra icons after `icon` in the title's icon row; see `Content`. */
  moreIcon1?: IconFunctionComponent;
  moreIcon2?: IconFunctionComponent;
  title: string | RichStr;
  description?: string | RichStr;
  children?: React.ReactNode;
  /**
   * Controls on the right of the title block, left to right. The header lays
   * them out as a top-aligned row with a 0.5rem gap. Each element needs a
   * `key`, as in any list.
   */
  actions?: React.ReactNode[];
  /**
   * Renders a secondary Cancel as the first action. `true` goes back in
   * history; a function overrides the destination.
   */
  cancel?: boolean | (() => void);
  divider?: boolean;
}

/**
 * Sticky header for settings pages. Shows a scroll shadow when the page
 * has scrolled. Headers with a Cancel or any `actions` are sticky; others
 * are not.
 */
function SettingsHeader({
  icon: Icon,
  moreIcon1,
  moreIcon2,
  title,
  description,
  children,
  actions,
  cancel,
  divider,
}: SettingsHeaderProps) {
  const router = useRouter();
  const strings = useOpalStrings();
  const [showShadow, setShowShadow] = useState(false);
  const headerRef = useRef<HTMLDivElement>(null);

  const onCancel =
    typeof cancel === "function"
      ? cancel
      : cancel
        ? () => router.back()
        : undefined;
  const hasActions = !!onCancel || (!!actions && actions.length > 0);
  const isSticky = hasActions;

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
        isSticky && "sticky top-0 z-settings-header bg-background-tint-01"
      )}
    >
      <Spacer rem={3.25} />

      <div className="flex flex-col gap-6 px-4">
        <div className="flex w-full items-start justify-between gap-4">
          <div aria-label="admin-page-title">
            <Content
              icon={Icon}
              moreIcon1={moreIcon1}
              moreIcon2={moreIcon2}
              title={title}
              description={description}
              sizePreset="headline"
              variant="heading"
            />
          </div>
          {hasActions && (
            <div className="flex shrink-0 items-start justify-end gap-2">
              {onCancel && (
                <Button prominence="secondary" onClick={onCancel}>
                  {strings.settingsHeaderCancel}
                </Button>
              )}
              {actions}
            </div>
          )}
        </div>

        {children}
      </div>

      {divider ? (
        <>
          <Spacer rem={1.5} />
          <Divider paddingParallel={4} paddingPerpendicular={0} />
        </>
      ) : (
        <Spacer rem={0.5} />
      )}

      {isSticky && (
        <div
          className={cn(
            "absolute start-0 end-0 h-2 pointer-events-none transition-opacity duration-300 rounded-b-08 opacity-0",
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
