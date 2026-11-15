import type { IconProps } from "@opal/types";
const SvgPowerpointFile = ({ size, ...props }: IconProps) => (
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
      d="M5.5 8.5V5H9C9.82843 5 10.5 5.67157 10.5 6.5V7C10.5 7.82843 9.82843 8.5 9 8.5H5.5ZM5.5 8.5V11M2 12.67V3.33C2 2.59546 2.59546 2 3.33 2H12.67C13.4045 2 14 2.59546 14 3.33V12.67C14 13.4045 13.4045 14 12.67 14H3.33C2.59546 14 2 13.4045 2 12.67Z"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgPowerpointFile;
