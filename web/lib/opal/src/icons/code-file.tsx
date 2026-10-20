import type { IconProps } from "@opal/types";
const SvgCodeFile = ({ size, ...props }: IconProps) => (
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
      d="M9.50002 9.99667L11.5 7.99667L9.5034 6.00004M6.49664 6.00004L4.50002 7.99667L6.49664 9.99329M2 12.67V3.33C2 2.59546 2.59546 2 3.33 2H12.67C13.4045 2 14 2.59546 14 3.33V12.67C14 13.4045 13.4045 14 12.67 14H3.33C2.59546 14 2 13.4045 2 12.67Z"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgCodeFile;
