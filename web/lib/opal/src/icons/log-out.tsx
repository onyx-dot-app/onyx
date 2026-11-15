import type { IconProps } from "@opal/types";
const SvgLogOut = ({ size, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 16 16"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    stroke="currentColor"
    {...props}
  >
    <path
      d="M6 14H3.33333C2.60711 14 2 13.3929 2 12.6667V3.33333C2 2.60711 2.60711 2 3.33333 2H6M10.6667 4.66667L14 8L10.6667 11.3333M14 8H6"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgLogOut;
