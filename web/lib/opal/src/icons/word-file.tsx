import type { IconProps } from "@opal/types";
const SvgWordFile = ({ size, ...props }: IconProps) => (
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
      d="M4.6 5L6 11H6.4L7.8 5L8.2 5L9.6 11H10L11.4 5M2 12.67V3.33C2 2.59546 2.59546 2 3.33 2H12.67C13.4045 2 14 2.59546 14 3.33V12.67C14 13.4045 13.4045 14 12.67 14H3.33C2.59546 14 2 13.4045 2 12.67Z"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgWordFile;
