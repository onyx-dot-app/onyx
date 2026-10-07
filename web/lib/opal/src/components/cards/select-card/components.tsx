import "@opal/components/cards/shared.css";
import "@opal/components/cards/select-card/styles.css";
import type { BorderVariants, Rounding, Spacing } from "@opal/types";
import { roundingToRem, spacingToRem } from "@opal/shared";
import { Interactive, type InteractiveStatefulProps } from "@opal/core";
import {
  CardFold,
  type CardFoldHeight,
} from "@opal/components/cards/fold/components";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/**
 * Props shared by both plain and expandable SelectCard modes.
 */
type SelectCardBaseProps = Omit<InteractiveStatefulProps, "variant"> & {
  /**
   * Padding.
   *
   * A spacing step: `N` is `N / 4` rem, so `4` is `1rem`.
   *
   * In expandable mode, applied **only** to the header. The `expandedContent`
   * slot has no intrinsic padding — callers own any padding inside the
   * content they pass in.
   *
   * @default 4
   */
  padding?: Spacing;

  /**
   * Border-radius preset.
   *
   * `N` is `N / 4` rem, so `rounding={2}` is the same distance as
   * `padding={2}`. `"full"` is a pill.
   *
   * In expandable mode when expanded, rounding applies only to the header's
   * top corners and the fold's bottom corners, so the two join seamlessly.
   *
   * @default 3
   */
  rounding?: Rounding;

  /**
   * Border style.
   * - `"none"`: no border.
   * - `"dashed"`: dashed border.
   * - `"solid"`: solid border.
   *
   * @default "solid"
   */
  border?: BorderVariants;

  /**
   * Ref forwarded to the root `<div>` — the card itself in plain mode, the
   * wrapper that holds the header and the fold in expandable mode.
   */
  ref?: React.Ref<HTMLDivElement>;

  /**
   * In plain mode, the card body. In expandable mode, the always-visible
   * header: the interactive part that stays put whether expanded or not.
   */
  children?: React.ReactNode;
};

type SelectCardPlainProps = SelectCardBaseProps & {
  /**
   * When `false` (or omitted), renders a plain card. No fold, no
   * `expandedContent` slot.
   *
   * @default false
   */
  expandable?: false;
};

type SelectCardExpandableProps = SelectCardBaseProps & {
  /**
   * Enables the expandable variant. Renders `children` as the interactive
   * header and `expandedContent` as the body that animates open and closed
   * with `expanded`.
   */
  expandable: true;

  /**
   * Controlled expanded state. The caller owns the state and the trigger —
   * SelectCard is purely visual here and never mutates this value.
   *
   * @default false
   */
  expanded?: boolean;

  /**
   * The expandable body, rendered below the header. It sits outside the
   * interactive element, so clicks and hovers inside it belong to whatever
   * the caller puts there rather than toggling the card.
   *
   * If `undefined`, the card looks exactly like a plain one.
   */
  expandedContent?: React.ReactNode;

  /**
   * Max-height constraint on the expandable content area, on Tailwind's
   * spacing scale: `N` is `N / 4` rem.
   * - `80` (default): caps at 20rem with vertical scroll.
   * - `"full"`: no max-height — content takes its natural height.
   *
   * @default 80
   */
  expandableContentHeight?: CardFoldHeight;
};

type SelectCardProps = SelectCardPlainProps | SelectCardExpandableProps;

// ---------------------------------------------------------------------------
// SelectCard
// ---------------------------------------------------------------------------

/**
 * A stateful interactive card — the card counterpart to `SelectButton`.
 *
 * Built on `Interactive.Stateful` (Slot) → a structural `<div>`. The
 * Stateful system owns background and foreground colors; the card owns
 * padding, rounding, border, and overflow.
 *
 * The root stays a `<div>` so children can be buttons and links, which HTML
 * forbids inside a `<button>`. A card with `onClick` still joins the tab
 * order, opens on Enter or Space, and paints like hover while
 * keyboard-focused. It takes no ARIA role of its own: a role would fold any
 * nested button into the card's accessible name.
 *
 * Children are fully composable — use `ContentAction`, `Content`, buttons,
 * `Interactive.Foldable`, etc. inside.
 *
 * Two mutually-exclusive modes:
 *
 * - **Plain** (default): one interactive card.
 * - **Expandable** (`expandable: true`): `children` become the interactive
 *   header and `expandedContent` an animating body below it, sharing the
 *   fold that `Card` uses. Only the header is interactive, so a form in the
 *   body keeps its own clicks. `state` is the caller's throughout: the card
 *   paints whatever state it is given, open or closed.
 *
 * @example Plain
 * ```tsx
 * <SelectCard state="selected" onClick={handleClick}>
 *   <ContentAction icon={SvgGlobe} title="Google" description="Search engine" />
 * </SelectCard>
 * ```
 *
 * @example Expandable, controlled
 * ```tsx
 * const [open, setOpen] = useState(false);
 * <SelectCard
 *   expandable
 *   expanded={open}
 *   expandedContent={<CredentialForm />}
 *   state="empty"
 *   onClick={() => setOpen((value) => !value)}
 * >
 *   <ContentAction icon={SvgPlusCircle} title="New account" />
 * </SelectCard>
 * ```
 */
function SelectCard(props: SelectCardProps) {
  if (props.expandable) {
    const {
      expanded = false,
      expandedContent,
      expandableContentHeight = 80,
      ...base
    } = props;
    return (
      <SelectCardShell
        {...base}
        fold={expandedContent}
        foldOpen={expanded && expandedContent !== undefined}
        foldHeight={expandableContentHeight}
      />
    );
  }
  return <SelectCardShell {...props} />;
}

// ---------------------------------------------------------------------------
// Shell — one place that builds the interactive header, for both modes
// ---------------------------------------------------------------------------

type SelectCardShellProps = SelectCardBaseProps & {
  /** Present only in expandable mode. */
  expandable?: boolean;
  /** The fold's content; `undefined` renders no fold at all. */
  fold?: React.ReactNode;
  /** Whether the fold is open, which flattens the header's bottom corners. */
  foldOpen?: boolean;
  foldHeight?: CardFoldHeight;
};

function SelectCardShell({
  padding: paddingProp = 4,
  rounding: roundingProp = 3,
  border = "solid",
  ref,
  children,
  onClick,
  onKeyDown,
  disabled,
  expandable,
  fold,
  foldOpen = false,
  foldHeight,
  ...statefulProps
}: SelectCardShellProps) {
  const paddingStyle = { padding: spacingToRem(paddingProp) };
  const radius = roundingToRem(roundingProp);
  // Expanded, the header rounds only at the top and the fold only at the
  // bottom, so the two halves read as one card rather than two.
  const headerRadius = foldOpen
    ? { borderTopLeftRadius: radius, borderTopRightRadius: radius }
    : { borderRadius: radius };

  // A caller with its own tab index (e.g. a roving radio group) keeps it.
  const isControl = !!onClick && !disabled;
  const controlProps = isControl
    ? {
        tabIndex: statefulProps.tabIndex ?? 0,
        onKeyDown: (event: React.KeyboardEvent<HTMLElement>) => {
          onKeyDown?.(event);
          if (event.defaultPrevented) return;
          // Keys pressed on a nested control belong to that control.
          if (event.target !== event.currentTarget) return;
          if (event.key !== "Enter" && event.key !== " ") return;
          event.preventDefault();
          event.currentTarget.click();
        },
      }
    : { onKeyDown };

  const header = (
    <Interactive.Stateful
      {...statefulProps}
      {...controlProps}
      onClick={onClick}
      disabled={disabled}
      variant="select-card"
    >
      <div
        ref={expandable ? undefined : ref}
        className="opal-select-card"
        style={{ ...paddingStyle, ...headerRadius }}
        data-border={border}
        data-opal-status-border="default"
      >
        {children}
      </div>
    </Interactive.Stateful>
  );

  if (!expandable) return header;

  return (
    <div ref={ref} className="opal-select-card-expandable">
      {header}
      {fold !== undefined && (
        <CardFold
          expanded={foldOpen}
          border={border}
          borderColor="default"
          radius={radius}
          contentHeight={foldHeight}
        >
          {fold}
        </CardFold>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Exports
// ---------------------------------------------------------------------------

export { SelectCard, type SelectCardProps };
