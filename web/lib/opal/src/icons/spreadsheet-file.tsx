import type { IconProps } from "@opal/types";
const SvgSpreadsheetFile = ({ size, ...props }: IconProps) => (
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
      d="M6 2V6M6 2H12.67C13.4045 2 14 2.59546 14 3.33V6M6 2H3.33C2.59546 2 2 2.59546 2 3.33V6M6 6V14M6 6H2M6 6H14M6 14H3.33C2.59546 14 2 13.4045 2 12.67V6M6 14H12.67C13.4045 14 14 13.4045 14 12.67V6"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgSpreadsheetFile;
