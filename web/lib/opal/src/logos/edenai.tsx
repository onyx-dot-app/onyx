import type { IconProps } from "@opal/types";

// Placeholder mark for Eden AI (the letters "EA"). Swap for the official
// Eden AI brand SVG when available.
const SvgEdenai = ({ size, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 48 48"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <title>Eden AI</title>
    <g fill="var(--text-05)">
      <rect x="8" y="6" width="6" height="36" />
      <rect x="8" y="6" width="18" height="6" />
      <rect x="8" y="21" width="15" height="6" />
      <rect x="8" y="36" width="18" height="6" />
      <polygon points="34,6 40,6 33,42 27,42" />
      <polygon points="34,6 40,6 47,42 41,42" />
      <rect x="31" y="27" width="12" height="6" />
    </g>
  </svg>
);

export default SvgEdenai;
