"use client";

import type { Route } from "next";
import { useNavigation } from "@opal/navigation/hooks";
import { cn } from "@opal/utils";
import { Divider, Button, Presence, Spacer } from "@opal/components";
import type { BadgeProps } from "@opal/components";
import type {
  IconFunctionComponent,
  RichStr,
  SizeVariants,
  Spacing,
  WithoutStyles,
} from "@opal/types";
import { spacingToRem } from "@opal/shared";
import {
  HtmlHTMLAttributes,
  createContext,
  useContext,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { Content } from "@opal/layouts";
import { useOpalStrings } from "@opal/strings";
// Imported from their own files: these indexes pull in @opal/layouts.
import { PageLoader } from "@opal/loaders/page-loader/components";
import { ErrorState } from "@opal/layouts/states/components";
import { toPlainString } from "@opal/components/text/InlineMarkdown";

// ---------------------------------------------------------------------------
// Root
// ---------------------------------------------------------------------------

const widthClasses: Record<
  Extract<SizeVariants, "sm" | "md" | "lg" | "xl" | "full">,
  string
> = {
  sm: "w-[min(var(--app-container-sm),100%)]",
  md: "w-[min(var(--app-container-md),100%)]",
  lg: "w-[min(var(--app-container-lg),100%)]",
  xl: "w-[min(var(--app-container-xl),100%)]",
  full: "w-(--app-container-full)",
};

/** The page failed to load: `true`, or a description of what went wrong. */
type SettingsPageError = boolean | string | RichStr;

/** The page's state, set on `Root` and read by `Body`. */
interface SettingsPageState {
  animateEnter: boolean;
  loading: boolean;
  error: SettingsPageError;
  /** The header's title as text, for the error title. */
  pageTitle: string;
  setPageTitle: (title: string) => void;
}

const SettingsPageContext = createContext<SettingsPageState>({
  animateEnter: true,
  loading: false,
  error: false,
  pageTitle: "",
  setPageTitle: () => {},
});

interface SettingsRootProps extends WithoutStyles<
  React.HtmlHTMLAttributes<HTMLDivElement>
> {
  width?: Extract<SizeVariants, "sm" | "md" | "lg" | "xl" | "full">;
  /**
   * The body animates in with `Presence` when the page mounts; the header does
   * not. `false` renders it at once. @default true
   */
  animateEnter?: boolean;
  /**
   * The body shows the page loader in place of its children. When it turns
   * false, the children mount and animate in, so the animation plays when
   * the content is ready. @default false
   */
  loading?: boolean;
  /**
   * The page failed to load. The body shows the standard error state in place
   * of its children, titled "{header title} failed to load". A string or
   * `markdown()` is its description; `true` uses a generic one. It wins over
   * `loading`. @default false
   */
  error?: SettingsPageError;
  /** Below 816 px of page width, the header and body keep 8 px side gutters in place of 16. @default false */
  narrowGutters?: boolean;
}

/**
 * Wrapper for settings pages. Creates a centered, scrollable container.
 * The `id="page-wrapper-scroll-container"` is referenced by `Header` for
 * scroll-shadow detection — do not remove it.
 */
function SettingsRoot({
  width = "md",
  animateEnter = true,
  loading = false,
  error = false,
  narrowGutters = false,
  ...props
}: SettingsRootProps) {
  // The header reports its title here, so the body's error state can name
  // the page.
  const [pageTitle, setPageTitle] = useState("");
  return (
    <SettingsPageContext.Provider
      value={{ animateEnter, loading, error, pageTitle, setPageTitle }}
    >
      {/* Both gutters stay reserved, so the centered page does not shift when content grows a scrollbar. */}
      <div
        id="page-wrapper-scroll-container"
        className="w-full h-full flex flex-col items-center overflow-y-auto [scrollbar-gutter:stable_both-edges]"
      >
        <div
          className={cn(
            "h-full",
            widthClasses[width],
            narrowGutters && "@container/settings-page"
          )}
        >
          <div {...props} />
        </div>
      </div>
    </SettingsPageContext.Provider>
  );
}

// ---------------------------------------------------------------------------
// Header
// ---------------------------------------------------------------------------

export interface SettingsHeaderProps {
  icon?: IconFunctionComponent;
  /** Extra icons after `icon` in the title's icon row; see `Content`. */
  moreIcon1?: IconFunctionComponent;
  moreIcon2?: IconFunctionComponent;
  title: string | RichStr;
  description?: string | RichStr;
  /** The title can be edited in place, as `Content` does it. */
  editable?: boolean;
  /** When the editable title shows its pencil: on hover, or at rest too. Default: `"hover"`. */
  editButton?: "hover" | "rest";
  /** Called when the user commits a title edit. */
  onTitleChange?: (newTitle: string) => void;
  children?: React.ReactNode;
  /**
   * Controls on the right of the title block, left to right. The header lays
   * them out as a top-aligned row with a 0.5rem gap. Each element needs a
   * `key`, as in any list.
   */
  actions?: React.ReactNode[];
  stackActionsOnMobile?: boolean;
  /**
   * Renders a secondary Cancel as the first action. `true` goes back within
   * the app (`clampedBack`), or to `/` when the page was not reached within
   * it; a path does the same with that path as the fallback; a function
   * replaces the action.
   */
  cancel?: boolean | string | (() => void);
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
  editable,
  editButton,
  onTitleChange,
  children,
  actions,
  stackActionsOnMobile = false,
  cancel = false,
  divider,
}: SettingsHeaderProps) {
  const navigation = useNavigation();
  const strings = useOpalStrings();
  const [showShadow, setShowShadow] = useState(false);
  const { setPageTitle } = useContext(SettingsPageContext);
  const titleText = toPlainString(title);
  // Before paint, so an error state on mount already has the page name.
  useLayoutEffect(() => {
    setPageTitle(titleText);
  }, [setPageTitle, titleText]);
  const headerRef = useRef<HTMLDivElement>(null);

  const onCancel =
    typeof cancel === "function"
      ? cancel
      : cancel === false
        ? undefined
        : () =>
            navigation.clampedBack(
              // SAFETY: a path on this origin (not `//host`) is a page of the
              // app; anything else falls back to the app's root.
              (typeof cancel === "string" &&
              cancel.startsWith("/") &&
              !cancel.startsWith("//")
                ? cancel
                : "/") as Route
            );
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

  // Sticky content in the body (e.g. a side panel) reads these to pin under the header and fit the visible height.
  useEffect(() => {
    const header = headerRef.current;
    const scrollContainer = document.getElementById(
      "page-wrapper-scroll-container"
    );
    if (!header || !scrollContainer) return;

    const publish = () => {
      scrollContainer.style.setProperty(
        "--settings-header-height",
        isSticky ? `${header.offsetHeight}px` : "0px"
      );
      scrollContainer.style.setProperty(
        "--settings-scroll-height",
        `${scrollContainer.clientHeight}px`
      );
    };

    publish();
    const resizeObserver = new ResizeObserver(publish);
    resizeObserver.observe(header);
    resizeObserver.observe(scrollContainer);

    return () => {
      resizeObserver.disconnect();
      scrollContainer.style.removeProperty("--settings-header-height");
      scrollContainer.style.removeProperty("--settings-scroll-height");
    };
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

      <div className="flex flex-col gap-6 px-4 @max-[51rem]/settings-page:px-2">
        <div
          className={cn(
            "flex w-full items-start justify-between gap-4",
            stackActionsOnMobile && "flex-col sm:flex-row"
          )}
        >
          <div aria-label="admin-page-title">
            <Content
              font="heading-headline"
              orientation="stacked"
              icon={Icon}
              moreIcon1={moreIcon1}
              moreIcon2={moreIcon2}
              title={title}
              description={description}
              editable={editable}
              editButton={editButton}
              onTitleChange={onTitleChange}
            />
          </div>
          {hasActions && (
            <div
              className={cn(
                "flex shrink-0 items-start justify-end gap-2",
                stackActionsOnMobile && "w-full sm:w-auto"
              )}
            >
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

      {/* No fade: an opacity transition here makes Chrome paint stale page content in this band. */}
      {isSticky && (
        <div
          className={cn(
            "absolute start-0 end-0 h-2 pointer-events-none rounded-b-08 opacity-0",
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

type SettingsBodyProps = WithoutStyles<HtmlHTMLAttributes<HTMLDivElement>> & {
  /** Space between sections, as a spacing step (`N / 4` rem). @default 8 */
  gap?: Spacing;
};

/** The page body. It renders the loading state and animation set on `Root`. */
function SettingsBody({ gap = 8, children, ...props }: SettingsBodyProps) {
  const { animateEnter, loading, error, pageTitle } =
    useContext(SettingsPageContext);
  const strings = useOpalStrings();
  const content = error ? (
    <ErrorState
      title={strings.settingsBodyErrorTitle(pageTitle)}
      description={error === true ? undefined : error}
    />
  ) : loading ? (
    <PageLoader />
  ) : (
    children
  );
  const body = (
    <div
      className="pt-6 pb-18 px-4 @max-[51rem]/settings-page:px-2 flex flex-col w-full"
      style={{ gap: spacingToRem(gap) }}
      {...props}
    >
      {content}
    </div>
  );
  // Only the content animates in; the error and loading states do not.
  return animateEnter && !error && !loading ? (
    <Presence>{body}</Presence>
  ) : (
    body
  );
}

// ---------------------------------------------------------------------------
// Loading
// ---------------------------------------------------------------------------

type SettingsLoadingProps = Pick<
  SettingsHeaderProps,
  "icon" | "title" | "description"
> &
  Pick<SettingsRootProps, "width">;

/**
 * A whole settings page while it loads: its header over the page loader. For
 * a route's `loading.tsx`, so it shows the page's title before the page.
 */
function SettingsLoading({
  icon,
  title,
  description,
  width,
}: SettingsLoadingProps) {
  return (
    <SettingsRoot width={width} loading>
      <SettingsHeader icon={icon} title={title} description={description} />
      <SettingsBody />
    </SettingsRoot>
  );
}

// ---------------------------------------------------------------------------
// Exports
// ---------------------------------------------------------------------------

export {
  SettingsRoot as Root,
  SettingsHeader as Header,
  SettingsBody as Body,
  SettingsLoading as Loading,
};
export type { SettingsLoadingProps };
