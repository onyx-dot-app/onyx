/**
 * Settings Page Layout Components
 *
 * A namespaced collection of components for building consistent settings pages.
 * These components provide a standardized layout with scroll-aware headers,
 * centered content containers, and automatic responsive behavior.
 *
 * @example
 * ```tsx
 * import Settings from "@/layouts/settings-pages";
 * import { SvgSettings } from "@opal/icons";
 *
 * function MySettingsPage() {
 *   return (
 *     <Settings.Root>
 *       <Settings.Header
 *         icon={SvgSettings}
 *         title="Account Settings"
 *         description="Manage your account preferences and settings"
 *         rightChildren={<Button>Save</Button>}
 *       >
 *         <InputTypeIn placeholder="Search settings..." />
 *       </Settings.Header>
 *
 *       <Settings.Body>
 *         <Card>Settings content here</Card>
 *       </Settings.Body>
 *     </Settings.Root>
 *   );
 * }
 * ```
 */

"use client";

import { cn } from "@/lib/utils";
import BackButton from "@/refresh-components/buttons/BackButton";
import Separator from "@/refresh-components/Separator";
import Spacer from "@/refresh-components/Spacer";
import Text from "@/refresh-components/texts/Text";
import { IconProps } from "@opal/types";
import { useEffect, useRef, useState } from "react";

/**
 * Settings Root Component
 *
 * Wrapper component that provides the base structure for settings pages.
 * Creates a centered, scrollable container with a maximum width of 50rem.
 *
 * Features:
 * - Full height container with centered content
 * - Automatic overflow-y scrolling
 * - Contains the scroll container ID that Settings.Header uses for shadow detection
 * - Maximum content width of 50rem (responsive)
 *
 * @example
 * ```tsx
 * <Settings.Root>
 *   <Settings.Header {...} />
 *   <Settings.Body>...</Settings.Body>
 * </Settings.Root>
 * ```
 */
export interface SettingsRootProps
  extends React.HtmlHTMLAttributes<HTMLDivElement> {}

function SettingsRoot(props: SettingsRootProps) {
  return (
    <div
      id="page-wrapper-scroll-container"
      className="w-full h-full flex flex-col items-center overflow-y-auto"
    >
      {/* WARNING: The id="page-wrapper-scroll-container" above is used by SettingsHeader
          to detect scroll position and show/hide the scroll shadow.
          DO NOT REMOVE this ID without updating SettingsHeader accordingly. */}
      <div className="h-full w-[min(50rem,100%)]">
        <div {...props} />
      </div>
    </div>
  );
}

/**
 * Settings Header Component
 *
 * Sticky header component for settings pages with icon, title, description,
 * and optional actions. Automatically shows a scroll shadow when the page
 * has been scrolled down.
 *
 * Features:
 * - Sticky positioning at the top of the page
 * - Icon display (1.75rem size)
 * - Title (headingH2 style)
 * - Optional description (secondary body text)
 * - Optional right-aligned action buttons via rightChildren
 * - Optional children content below title/description
 * - Optional back button
 * - Optional bottom separator
 * - Automatic scroll shadow effect
 *
 * @example
 * ```tsx
 * // Basic header
 * <Settings.Header
 *   icon={SvgUser}
 *   title="Profile Settings"
 *   description="Update your profile information"
 * />
 *
 * // Without description
 * <Settings.Header
 *   icon={SvgUser}
 *   title="Profile Settings"
 * />
 *
 * // With action buttons
 * <Settings.Header
 *   icon={SvgSettings}
 *   title="General Settings"
 *   description="Configure your preferences"
 *   rightChildren={
 *     <Button onClick={handleSave}>Save Changes</Button>
 *   }
 * />
 *
 * // With search/filter below and bottom separator
 * <Settings.Header
 *   icon={SvgDatabase}
 *   title="Data Sources"
 *   description="Manage your connected data sources"
 *   includeBottomSeparator
 * >
 *   <InputTypeIn placeholder="Search data sources..." />
 * </Settings.Header>
 *
 * // With back button
 * <Settings.Header
 *   icon={SvgArrow}
 *   title="Advanced Settings"
 *   description="Expert configuration options"
 *   renderBackButton
 * />
 * ```
 */
export interface SettingsHeaderProps {
  icon: React.FunctionComponent<IconProps>;
  title: string;
  description?: React.ReactNode;
  children?: React.ReactNode;
  rightChildren?: React.ReactNode;
  backButton?: boolean;
  separator?: boolean;
}

function SettingsHeader({
  icon: Icon,
  title,
  description,
  children,
  rightChildren,
  backButton,
  separator,
}: SettingsHeaderProps) {
  const [showShadow, setShowShadow] = useState(false);
  const headerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // IMPORTANT: This component relies on SettingsRoot having the ID "page-wrapper-scroll-container"
    // on its scrollable container. If that ID is removed or changed, the scroll shadow will not work.
    const scrollContainer = document.getElementById(
      "page-wrapper-scroll-container"
    );
    if (!scrollContainer) return;

    const handleScroll = () => {
      // Show shadow if the scroll container has been scrolled down
      setShowShadow(scrollContainer.scrollTop > 0);
    };

    scrollContainer.addEventListener("scroll", handleScroll);
    handleScroll(); // Check initial state

    return () => scrollContainer.removeEventListener("scroll", handleScroll);
  }, []);

  return (
    <div
      ref={headerRef}
      className={cn(
        "sticky top-0 z-10 w-full bg-background-tint-01",
        backButton ? "pt-4" : "pt-10"
      )}
    >
      {backButton && (
        <div className="px-2">
          <BackButton />
        </div>
      )}
      <div
        className={cn("flex flex-col gap-6 px-4", backButton ? "pt-2" : "pt-4")}
      >
        <div className="flex flex-col">
          <div className="flex flex-row justify-between items-center gap-4">
            <Icon className="stroke-text-04 h-[1.75rem] w-[1.75rem]" />
            {rightChildren}
          </div>
          <div className="flex flex-col">
            <Text headingH2>{title}</Text>
            {description &&
              (typeof description === "string" ? (
                <Text secondaryBody text03>
                  {description}
                </Text>
              ) : (
                description
              ))}
          </div>
        </div>
        {children}
      </div>
      {separator && (
        <>
          <Spacer rem={1.5} />
          <Separator noPadding className="px-4" />
        </>
      )}
      <div
        className={cn(
          "absolute left-0 right-0 h-[0.5rem] pointer-events-none transition-opacity duration-300 rounded-b-08 opacity-0",
          showShadow && "opacity-100"
        )}
        style={{
          background: "linear-gradient(to bottom, var(--mask-02), transparent)",
        }}
      />
    </div>
  );
}

/**
 * Settings Body Component
 *
 * Content container for settings page body. Provides consistent padding
 * and vertical spacing for content sections.
 *
 * Features:
 * - Vertical padding: 1.5rem (py-6)
 * - Horizontal padding: 1rem (px-4)
 * - Flex column layout with 2rem gap (gap-8)
 * - Full width container
 *
 * @example
 * ```tsx
 * // Basic usage
 * <Settings.Body>
 *   <Card>
 *     <h3>Section 1</h3>
 *     <p>Content here</p>
 *   </Card>
 *   <Card>
 *     <h3>Section 2</h3>
 *     <p>More content</p>
 *   </Card>
 * </Settings.Body>
 *
 * // Custom spacing
 * <Settings.Body className="gap-4">
 *   <Card>Tighter spacing</Card>
 * </Settings.Body>
 *
 * // No padding
 * <Settings.Body className="p-0">
 *   <FullWidthComponent />
 * </Settings.Body>
 * ```
 */
export interface SettingsBodyProps {
  children: React.ReactNode;
}

function SettingsBody({ children }: SettingsBodyProps) {
  return (
    <div className="pt-6 pb-[4.5rem] px-4 flex flex-col gap-8 w-full">
      {children}
    </div>
  );
}

const Settings = {
  Root: SettingsRoot,
  Header: SettingsHeader,
  Body: SettingsBody,
};

export default Settings;
