import type { IconProps } from "@opal/types";

const SvgCreateAgent = ({ size, ...props }: IconProps) => (
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
      d="M4.5 2.5L8 1L11.5 2.5M13.5 4.5L15 8L13.5 11.5M11.5 13.5L8 15L4.5 13.5M2.5 11.5L1 7.99999L2.5 4.5"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
    <path
      d="M5 8L8 8.00001M8 8.00001L11 8.00001M8 8.00001L8 5M8 8.00001L8 11"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgCreateAgent;
