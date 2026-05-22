import type { IconProps } from "@opal/types";
const SvgVideoFile = ({ size, ...props }: IconProps) => (
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
      d="M2 3.33V12.67C2 13.4045 2.59546 14 3.33 14H12.67C13.4045 14 14 13.4045 14 12.67V3.33C14 2.59546 13.4045 2 12.67 2H3.33C2.59546 2 2 2.59546 2 3.33Z"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
    <path
      d="M6 5L11 8L6 11V5Z"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgVideoFile;
