import { Path } from "react-native-svg";

import { Icon, type IconProps } from "@/components/icons/Icon";

// Ported from web/lib/opal/src/icons/sliders.tsx (stroke-based, viewBox 16). The
// web SVG wraps the path in a full-viewBox clipPath (a no-op), so only the path
// is ported here, matching the other icons.
/** Sliders — actions popover trigger. */
function SvgSliders(props: IconProps) {
  return (
    <Icon viewBox="0 0 16 16" {...props}>
      {({ color }) => (
        <Path
          d="M2.66666 14V9.33333M2.66666 6.66667V2M7.99999 14V8M7.99999 5.33333V2M13.3333 14V10.6667M13.3333 8V2M0.666656 9.33333H4.66666M5.99999 5.33333H9.99999M11.3333 10.6667H15.3333"
          stroke={color}
          strokeWidth={1.5}
          strokeLinecap="round"
          strokeLinejoin="round"
          fill="none"
        />
      )}
    </Icon>
  );
}

export { SvgSliders };
