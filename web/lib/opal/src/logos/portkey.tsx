import type { IconProps } from "@opal/types";

// PLACEHOLDER Portkey mark — pending the official brand SVG. Drawn monochrome
// via var(--text-05) so it adapts to the theme; replace the <path> below with
// the official Portkey artwork (inlined, self-contained) when available.
const SvgPortkey = ({ size, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <title>Portkey</title>
    <path
      d="M12 2.5 20.5 7v10L12 21.5 3.5 17V7L12 2.5Z"
      stroke="var(--text-05)"
      strokeWidth="1.5"
      strokeLinejoin="round"
    />
    <path
      d="m10 8.5 4 3.5-4 3.5"
      stroke="var(--text-05)"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

export default SvgPortkey;
