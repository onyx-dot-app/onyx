import type { IconProps } from "@opal/types";
const SvgImport = ({ size, ...props }: IconProps) => (
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
      d="M7.5 5.33333L10.1667 8L7.5 10.6667M10.1667 8L1.5 7.99667M3.5 5V3.33C3.5 2.59546 4.09546 2 4.83 2H12.1667C12.8929 2 13.5 2.60711 13.5 3.33333V12.6667C13.5 13.3929 12.8929 14 12.1667 14H4.83C4.09546 14 3.5 13.4045 3.5 12.67V11"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgImport;
