import type { IconProps } from "@opal/types";
const SvgTextLines = ({ size, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 18 18"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    stroke="currentColor"
    {...props}
  >
    <path
      d="M15.75 7.4925H2.25M15.75 4.5H2.25M9 13.5H2.25M15.75 10.4962H2.25"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgTextLines;
