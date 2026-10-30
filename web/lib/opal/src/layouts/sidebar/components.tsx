"use client";

import "@opal/layouts/sidebar/styles.css";
import useHotkey from "@opal/hooks/useHotkey";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
} from "react";
import { usePathname } from "next/navigation";
import {
  Button,
  Divider,
  ShadowDiv,
  Spacer,
  Text,
  Tooltip,
} from "@opal/components";
import { iconWrapper } from "@opal/components/buttons/icon-wrapper";
import { Tag, type TagProps } from "@opal/components";
import { Disabled, Hoverable, Interactive } from "@opal/core";
import { SvgSidebar } from "@opal/icons";
import type { IconFunctionComponent, RichStr } from "@opal/types";
import { useSidebarState } from "@opal/layouts/root/components";
import { SidebarFoldedContext } from "@opal/layouts/sidebar/context";
import useScreenSize from "@opal/hooks/useScreenSize";
import { useOpalStrings } from "@opal/strings";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const SCROLL_POSITION_PREFIX = "opal-sidebar-scroll-";
const SIDEBAR_LOGO_HEIGHT_PX = 28;

// ---------------------------------------------------------------------------
// Root
// ---------------------------------------------------------------------------

const SidebarFoldableContext = createContext(false);

interface SidebarRootProps {
  /**
   * Whether the sidebar supports folding on desktop.
   * When `false` (the default), the sidebar is always expanded on desktop and
   * the fold button is hidden. Mobile overlay behavior is always enabled
   * regardless of this prop.
   */
  foldable?: boolean;
  children: React.ReactNode;
}

function SidebarRoot({ foldable = false, children }: SidebarRootProps) {
  const { isMobile, isSmallScreen, isMounted } = useScreenSize();
  const { folded, setFolded } = useSidebarState();

  const closeSidebar = useCallback(() => setFolded(true), [setFolded]);

  // ⌘E / Ctrl+E folds a foldable sidebar. A non-foldable one ignores it, so
  // its fold state never changes behind it.
  useHotkey("mod+e", () => setFolded((prev) => !prev), { enabled: foldable });

  useEffect(() => {
    // Before mount the screen size reports desktop. Act on the real size only,
    // or every mount unfolds the overlay on mobile and small screens.
    if (!isMounted) return;

    if (isMobile || isSmallScreen) {
      // The overlay hides the page behind it, so it starts closed.
      setFolded(true);
    } else if (!foldable) {
      // A non-foldable desktop sidebar is a column that is always open.
      setFolded(false);
    }
  }, [isMounted, isMobile, isSmallScreen, foldable, setFolded]);

  const foldedAttr = String(folded);

  // The overlays always fold; a desktop column only folds when `foldable`.
  // Tabs read this derived value, not the app-wide raw state, so tabs outside
  // a sidebar (and inside a non-foldable one) never collapse.
  const effectiveFolded = (isMobile || isSmallScreen || foldable) && folded;

  // The same value in two forms: context for the parts that need JS (the
  // folded-only tooltip), and `data-folded` for the parts CSS can do on its
  // own. The attribute lets descendants restyle without re-rendering.
  const inner = (
    <SidebarFoldedContext.Provider value={effectiveFolded}>
      <div
        className="opal-sidebar-root__inner"
        data-folded={String(effectiveFolded)}
      >
        {children}
      </div>
    </SidebarFoldedContext.Provider>
  );

  if (isMobile) {
    return (
      <SidebarFoldableContext.Provider value={true}>
        <div
          className="opal-sidebar-root__overlay"
          data-variant="mobile"
          data-folded={foldedAttr}
        >
          {inner}
        </div>
        <div
          // Pointer convenience only — the fold button dismisses via keyboard.
          role="presentation"
          className="opal-sidebar-root__backdrop"
          data-variant="mobile"
          data-folded={foldedAttr}
          onClick={closeSidebar}
        />
      </SidebarFoldableContext.Provider>
    );
  }

  if (isSmallScreen) {
    return (
      <SidebarFoldableContext.Provider value={true}>
        <div className="opal-sidebar-root__spacer" />
        <div
          className="opal-sidebar-root__overlay"
          data-variant="small"
          data-folded={foldedAttr}
        >
          {inner}
        </div>
        <div
          // Pointer convenience only — the fold button dismisses via keyboard.
          role="presentation"
          className="opal-sidebar-root__backdrop"
          data-variant="small"
          data-folded={foldedAttr}
          onClick={closeSidebar}
        />
      </SidebarFoldableContext.Provider>
    );
  }

  return (
    <SidebarFoldableContext.Provider value={foldable}>
      <div
        className="opal-sidebar-root__column"
        data-folded={foldable ? foldedAttr : undefined}
      >
        {inner}
      </div>
    </SidebarFoldableContext.Provider>
  );
}

// ---------------------------------------------------------------------------
// Header — topbar (logo + fold button) with optional pinned content below
// ---------------------------------------------------------------------------

/** The header's branding: a logo factory, or a mark and a wordmark. */
type SidebarHeaderBrandingProps =
  | {
      /**
       * Logo factory. Receives the effective fold state and returns an
       * `IconFunctionComponent` that is rendered at `size={28}` in the topbar.
       */
      renderAppLogo: (folded: boolean) => IconFunctionComponent;
      logo?: never;
      wordmark?: never;
    }
  | {
      renderAppLogo?: never;
      /** The logo mark, shown in both fold states. */
      logo: React.ReactNode;
      /**
       * The name beside the mark. It fades in place as the sidebar folds,
       * while the fold button, anchored to the row's end, moves with the
       * column's edge. Folded, the fold button takes the mark's place on
       * hover, keyboard focus, or a device without hover.
       */
      wordmark: React.ReactNode;
    };

type SidebarHeaderProps = SidebarHeaderBrandingProps & {
  /**
   * When `true` (default), the logo is shown in the folded state with a
   * hover-to-reveal fold button. When `false`, only the fold button is shown
   * when folded.
   */
  showLogoWhenFolded?: boolean;
  children?: React.ReactNode;
};

function SidebarHeader(props: SidebarHeaderProps) {
  const { showLogoWhenFolded = true, children } = props;
  const foldable = useContext(SidebarFoldableContext);
  const { folded, setFolded } = useSidebarState();
  const strings = useOpalStrings();
  const toggleFolded = useCallback(
    () => setFolded((prev) => !prev),
    [setFolded]
  );

  const foldLabel = folded ? strings.sidebarOpen : strings.sidebarClose;

  const closeButton = useMemo(
    () => (
      <Button
        icon={SvgSidebar}
        prominence="tertiary"
        aria-label={foldLabel}
        tooltip={foldLabel}
        // Sidebar tooltips open toward the page, in both fold states.
        tooltipSide="end"
        size="md"
        onClick={toggleFolded}
      />
    ),
    [folded, foldLabel, toggleFolded]
  );

  if (props.renderAppLogo === undefined) {
    return (
      <div className="opal-sidebar-header">
        <div className="opal-sidebar-header__topbar">
          <div
            className="opal-sidebar-header__brand"
            data-foldable={foldable || undefined}
            // Folded without the logo, the fold button stays shown.
            data-logo-when-folded={showLogoWhenFolded}
            style={
              {
                "--sidebar-logo-size": `${SIDEBAR_LOGO_HEIGHT_PX}px`,
              } as React.CSSProperties
            }
          >
            <div className="opal-sidebar-header__mark">{props.logo}</div>
            <div className="opal-sidebar-header__wordmark">
              {props.wordmark}
            </div>
            {foldable && (
              <div className="opal-sidebar-header__fold-button">
                {closeButton}
              </div>
            )}
          </div>
        </div>
        {children && (
          <div className="opal-sidebar-header__content">{children}</div>
        )}
      </div>
    );
  }

  const Logo = props.renderAppLogo(foldable ? folded : false);
  const logoEl = <Logo size={SIDEBAR_LOGO_HEIGHT_PX} />;

  // Folded: the logo *is* the unfold control. The fold icon swaps in on hover
  // (and on keyboard focus), but the button underneath never changes, so the
  // sidebar can still be opened where there is no hover to reveal anything —
  // touch devices and keyboard navigation.
  const foldedLogoButton = (
    <Tooltip tooltip={foldLabel} side="end">
      <Interactive.Stateless
        prominence="tertiary"
        type="button"
        onClick={toggleFolded}
      >
        <Interactive.Container
          type="button"
          size="fit"
          rounding={2}
          aria-label={foldLabel}
        >
          <div
            className="opal-sidebar-header__logo-swap"
            style={{
              height: SIDEBAR_LOGO_HEIGHT_PX,
              width: SIDEBAR_LOGO_HEIGHT_PX,
            }}
          >
            <div className="opal-sidebar-header__logo-rest">{logoEl}</div>
            <div className="opal-sidebar-header__logo-fold">
              {iconWrapper(SvgSidebar, "md", false)}
            </div>
          </div>
        </Interactive.Container>
      </Interactive.Stateless>
    </Tooltip>
  );

  return (
    <div className="opal-sidebar-header">
      <div className="opal-sidebar-header__topbar">
        <div className="opal-sidebar-header__topbar-inner">
          {!foldable ? (
            logoEl
          ) : folded && showLogoWhenFolded ? (
            foldedLogoButton
          ) : folded ? (
            closeButton
          ) : (
            <>
              {logoEl}
              {closeButton}
            </>
          )}
        </div>
      </div>
      {children && (
        <div className="opal-sidebar-header__content">{children}</div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Body — scrollable content area with scroll-position persistence
// ---------------------------------------------------------------------------

interface SidebarBodyProps {
  /**
   * Unique key to enable scroll position persistence across navigation.
   * (e.g., "admin-sidebar", "app-sidebar").
   */
  scrollKey: string;
  children?: React.ReactNode;
}

function SidebarBody({ scrollKey, children }: SidebarBodyProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const pathname = usePathname();

  useEffect(() => {
    const scrollElement = scrollRef.current;
    if (!scrollElement) return;

    const storageKey = `${SCROLL_POSITION_PREFIX}${scrollKey}`;
    const handleScroll = () => {
      sessionStorage.setItem(storageKey, scrollElement.scrollTop.toString());
    };

    scrollElement.addEventListener("scroll", handleScroll, { passive: true });
    return () => scrollElement.removeEventListener("scroll", handleScroll);
  }, [scrollKey]);

  useLayoutEffect(() => {
    const scrollElement = scrollRef.current;
    if (!scrollElement) return;

    const storageKey = `${SCROLL_POSITION_PREFIX}${scrollKey}`;
    const savedPosition = parseInt(
      sessionStorage.getItem(storageKey) || "0",
      10
    );
    scrollElement.scrollTop = savedPosition;
  }, [pathname, scrollKey]);

  return (
    <ShadowDiv
      variant="mask"
      scrollContainerRef={scrollRef}
      containerClassName="opal-sidebar-body"
      className="opal-sidebar-body__scroll"
    >
      {/* Hidden while folded — see styles.css. The fold state comes from the
          `data-folded` attribute on the root, so folding re-renders nothing
          here. */}
      <div className="opal-sidebar-body__content">{children}</div>
      <div className="opal-sidebar-body__spacer" />
    </ShadowDiv>
  );
}

// ---------------------------------------------------------------------------
// Footer — pinned content below the scroll area
// ---------------------------------------------------------------------------

interface SidebarFooterProps {
  children?: React.ReactNode;
}

function SidebarFooter({ children }: SidebarFooterProps) {
  return <div className="opal-sidebar-footer">{children}</div>;
}

// ---------------------------------------------------------------------------
// Section — titled group within the scrollable body
// ---------------------------------------------------------------------------

interface SidebarSectionProps {
  title?: string | RichStr;
  /** Optional tag at the end of the header, in line with tab `rightChildren`. */
  tag?: TagProps;
  /** Optional action shown on hover, e.g. a "+" button. */
  action?: React.ReactNode;
  /** When true, dims the section header to indicate it is unavailable. */
  disabled?: boolean;

  children?: React.ReactNode;
}

function SidebarSection({
  title,
  tag,
  action,
  disabled,
  children,
}: SidebarSectionProps) {
  return (
    <div className="flex flex-col">
      {title ? (
        <Hoverable.Root group="sidebar-section">
          <Disabled disabled={disabled}>
            <div className="opal-sidebar-section__header">
              <div className="opal-sidebar-section__title">
                <Text font="secondary-body" color="text-02">
                  {title}
                </Text>
              </div>
              {tag && (
                <div className="opal-sidebar-section__tag">
                  <Tag {...tag} />
                </div>
              )}
              {action && (
                <Hoverable.Item group="sidebar-section">
                  {action}
                </Hoverable.Item>
              )}
            </div>
          </Disabled>
        </Hoverable.Root>
      ) : (
        <Spacer rem={1} />
      )}
      {children}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Divider — horizontal rule between groups in the sidebar
// ---------------------------------------------------------------------------

function SidebarDivider() {
  return <Divider paddingParallel={2} paddingPerpendicular={2} />;
}

// ---------------------------------------------------------------------------
// Exports
// ---------------------------------------------------------------------------

export {
  SidebarRoot as Root,
  SidebarHeader as Header,
  SidebarBody as Body,
  SidebarFooter as Footer,
  SidebarSection as Section,
  SidebarDivider as Divider,
};
export type { SidebarRootProps };
