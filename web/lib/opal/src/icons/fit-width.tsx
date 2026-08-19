import type { IconProps } from "@opal/types";
const SvgFitWidth = ({ size, ...props }: IconProps) => (
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
      d="M4.5 8H5.5M2.5 2.5V13.5M11.5 8H10.5M13.5 2.5V13.5M7.5 8H8.5"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgFitWidth;
