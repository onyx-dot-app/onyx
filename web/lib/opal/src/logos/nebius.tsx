import type { IconProps } from "@opal/types";

// Nebius Token Factory mark — the brand "N" glyph on the brand's lime tile
// (its official light lockup, matching the admin mocks). The lime tile keeps
// the mark legible on both light and dark provider-card backgrounds; colors are
// inlined (like the other brand logos) rather than a Tailwind text-color class,
// so the mark renders identically regardless of theme.
const SvgNebius = ({ size, className, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 28 28"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    className={className}
    {...props}
  >
    <title>Nebius TokenFactory</title>
    <rect width="28" height="28" rx="6.5" fill="#E0FF4F" />
    <g
      transform="translate(6.5 6.5) scale(0.625)"
      fill="#0B0B0B"
      fillRule="evenodd"
    >
      <path d="M20 2.306v16.797s4-.242 4-4.815V2.306h-4zM4 22.001V5.204s-4 .242-4 4.816V22h4z" />
      <path d="M16.318 16.51L11.286 4.94c-.824-1.872-2.168-2.926-4.077-2.926-1.908 0-3.211 1.54-3.211 3.19 0 0 2.405-.333 3.68 2.593l5.036 11.57c.821 1.87 2.168 2.926 4.075 2.926 1.905 0 3.211-1.541 3.211-3.19 0 0-2.406.333-3.682-2.594z" />
    </g>
  </svg>
);

export default SvgNebius;
