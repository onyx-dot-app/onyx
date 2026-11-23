"use client";

import "@opal/components/icon-container/styles.css";
import { useState } from "react";
import type { IconFunctionComponent } from "@opal/types";
import { SvgUser } from "@opal/icons";

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

/**
 * Content union: a bare glyph, the light circle around a required icon, or
 * the user circle with a photo or initials. Invalid combinations
 * (an avatar circle without its content) are type errors.
 */
type IconContainerContentProps =
  | {
      avatar?: undefined;

      /**
       * Glyph for the bare icon content. Logo components from `@opal/logos`
       * work here too.
       */
      icon?: IconFunctionComponent;
      initials?: never;
      src?: never;
      diameter?: never;
    }
  | {
      /** Light circle around `icon`. */
      avatar: "icon";
      icon: IconFunctionComponent;
      initials?: never;
      src?: never;
      diameter?: never;
    }
  | {
      /** User circle: the photo, else the initials, else a person glyph. */
      avatar: "user";

      /**
       * Up to two letters, shown on the dark circle when there is no photo.
       * Null shows a person glyph on a light circle.
       */
      initials: string | null;

      /** Photo URL. The initials show when it is missing or fails to load. */
      src?: string | null;

      /** Circle diameter in pixels, for avatars outside the size presets. */
      diameter?: number;
      icon?: never;
    };

type IconContainerProps = IconContainerContentProps & {
  /** Size preset, keyed to the line-height scale of the matching text role. */
  size?: IconContainerSize;

  /**
   * Reading prominence: `"entity"` renders in `text-04` at every size.
   * `"action"` has no styles of its own, it only emits `data-type="action"`
   * as a hook for interactive contexts.
   */
  type?: IconContainerType;
};

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
  initials,
  src,
  diameter,
}: IconContainerProps) {
  // Keyed by URL, so a new photo URL tries again after a failure.
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  const glyph = Icon ? <Icon className="opal-icon-container-glyph" /> : null;
  const diameterStyle = diameter
    ? { width: `${diameter / 16}rem`, height: `${diameter / 16}rem` }
    : undefined;

  let content: React.ReactNode = glyph;
  if (avatar === "user") {
    const showPhoto = !!src && src !== failedSrc;
    content = (
      <div
        className="opal-icon-container-avatar opal-icon-container-avatar-user"
        data-empty={!showPhoto && !initials ? "true" : undefined}
        style={diameterStyle}
      >
        {showPhoto ? (
          <img
            src={src}
            alt=""
            className="opal-icon-container-avatar-image"
            onError={() => setFailedSrc(src)}
          />
        ) : initials ? (
          <span className="opal-icon-container-avatar-initials">
            {initials}
          </span>
        ) : (
          <SvgUser className="opal-icon-container-avatar-empty-glyph" />
        )}
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
    <div
      className="opal-icon-container"
      data-size={size}
      data-type={type}
      style={diameterStyle}
    >
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
