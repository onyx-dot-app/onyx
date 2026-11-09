import type { IconProps } from "@opal/types";
const SvgListCheck = ({ size, ...props }: IconProps) => (
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
      d="M8.75 5H14M8.5 11H14M2 5L3.5 6.5L6.5 3.5M5.75 9.25V12.75H2.25V9.25H5.75Z"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgListCheck;
