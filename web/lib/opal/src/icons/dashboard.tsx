import type { IconProps } from "@opal/types";

const SvgDashboard = ({ size, ...props }: IconProps) => (
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
      d="M14 6V3.33333C14 2.59695 13.403 2 12.6667 2H3.33333C2.59695 2 2 2.59695 2 3.33333V6M14 6V12.6667C14 13.403 13.403 14 12.6667 14H6M14 6H6M2 6V12.6667C2 13.403 2.59695 14 3.33333 14H6M2 6H6M6 6V14"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgDashboard;
