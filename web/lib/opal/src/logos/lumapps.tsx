import type { IconProps } from "@opal/types";

// LumApps brand mark (the isometric-cube glyph). Square viewBox so it renders
// cleanly in connector tiles; `currentColor` lets it adapt to light/dark.
const SvgLumapps = ({ size, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 -0.22 28.33 28.33"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <path
      d="M6.197 0L0 3.54V10.623L4.869 13.437V6.31L11.017 2.781L6.197 0ZM7.97 18.666V24.323L14.167 27.886L20.364 24.323V18.666L14.167 22.223L7.97 18.666ZM7.97 8.146V15.229L14.167 18.769L20.364 15.229V8.146L14.167 4.606L7.97 8.146ZM17.318 2.783L23.461 6.306V13.434L28.33 10.62V3.54L22.13 0L17.318 2.783Z"
      fill="currentColor"
    />
  </svg>
);

export default SvgLumapps;
