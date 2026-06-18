// Why this exists: React Native has no CSS engine, so a react-native-svg icon can't
// read a Tailwind class like `text-text-02` (on web the browser does this for free).
// This wrapper is that missing translator — it turns a color class into a real color
// and hands it to the icon, so icons use the same design tokens as everything else.
//
// How: `cssInterop` compiles the className and maps the resolved text color → the
// icon's `color` prop, which the SVG's `stroke="currentColor"` reads. Adds a default
// size (16) + color (`text-text-03`).
import { cssInterop } from "nativewind";

import { cn } from "@/lib/utils";
import type { IconFunctionComponent, IconProps } from "@/icons/types";

type IconWrapperProps = IconProps & {
  as: IconFunctionComponent;
};

function IconImpl({ as: IconComponent, ...props }: IconWrapperProps) {
  return <IconComponent {...props} />;
}

cssInterop(IconImpl, {
  className: {
    target: "style",
    nativeStyleToProp: { color: true },
  },
});

/**
 * @example
 * import SvgSearch from "@/icons/search";
 * <Icon as={SvgSearch} size={16} className="text-text-02" />
 */
function Icon({ as, className, size = 16, ...props }: IconWrapperProps) {
  return (
    <IconImpl
      as={as}
      className={cn("text-text-03", className)}
      size={size}
      {...props}
    />
  );
}

export { Icon };
