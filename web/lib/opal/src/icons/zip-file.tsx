import type { IconProps } from "@opal/types";
const SvgZipFile = ({ size, ...props }: IconProps) => (
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
      d="M5.5 4.25H6M7 5.75H7.5M6 7.25H5.5M7.5 8.75H7M5.5 10.25H6M7.5 11.75H7M5.5 13.25H6M7.5 2.75H7M2 12.67V3.33C2 2.59546 2.59546 2 3.33 2H12.67C13.4045 2 14 2.59546 14 3.33V12.67C14 13.4045 13.4045 14 12.67 14H3.33C2.59546 14 2 13.4045 2 12.67Z"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgZipFile;
