import type { IconProps } from "@opal/types";
const SvgSlidesFile = ({ size, ...props }: IconProps) => (
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
      d="M4 5.25V10.75H12V5.25H4Z"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgSlidesFile;
