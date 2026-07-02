// RN has no CSS engine: `cssInterop` resolves the text-color class to a real color and
// maps it onto the icon's `color` prop, which the SVG's `stroke="currentColor"` reads.
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
