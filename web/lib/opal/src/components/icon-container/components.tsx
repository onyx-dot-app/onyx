import "@opal/components/icon-container/styles.css";
import type { IconFunctionComponent } from "@opal/types";
import { Text } from "@opal/components";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type IconContainerSize =
  | "secondary"
  | "main-ui"
  | "main-content"
  | "section"
  | "sub-headline";

type IconContainerType = "default" | "entity" | "action";

interface IconContainerProps {
  /** Size preset, keyed to the line-height scale of the matching text role. */
  size?: IconContainerSize;

  /**
   * Reading prominence: `"entity"` renders in `text-04` at every size.
   * `"action"` has no styles of its own, it only emits `data-type="action"`
   * as a hook for interactive contexts.
   */
  type?: IconContainerType;

  /**
   * Glyph for the bare icon content, or the circle's glyph with
   * `avatar="icon"`. Logo components from `@opal/logos` work here too.
   */
  icon?: IconFunctionComponent;

  /**
   * Renders the round avatar: `"user"` is the dark circle with the initial
   * of `name`, `"icon"` is the light circle around `icon`.
   */
  avatar?: "user" | "icon";

  /** Initial source for `avatar="user"`. */
  name?: string;
}

// ---------------------------------------------------------------------------
// IconContainer
// ---------------------------------------------------------------------------

/**
 * Fixed-size icon slot (Figma Icon Container): a bare glyph, or the round
 * avatar holding a user initial or an icon. The one primitive behind
 * avatars, icon-in-circle badges, and logo slots.
 */
function IconContainer({
  size = "main-ui",
  type = "default",
  icon: Icon,
  avatar,
  name,
}: IconContainerProps) {
  const glyph = Icon ? <Icon className="opal-icon-container-glyph" /> : null;

  let content: React.ReactNode = glyph;
  if (avatar === "user") {
    const initial = (name?.trim()[0] ?? "?").toUpperCase();
    content = (
      <div className="opal-icon-container-avatar opal-icon-container-avatar-user">
        <Text font="secondary-action" color="text-inverted-05" nowrap>
          {initial}
        </Text>
      </div>
    );
  } else if (avatar === "icon") {
    content = (
      <div className="opal-icon-container-avatar opal-icon-container-avatar-icon">
        {glyph}
      </div>
    );
  }

  return (
    <div className="opal-icon-container" data-size={size} data-type={type}>
      {content}
    </div>
  );
}

export {
  IconContainer,
  type IconContainerProps,
  type IconContainerSize,
  type IconContainerType,
};
