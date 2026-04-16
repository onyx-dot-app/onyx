import type { IconProps } from "@opal/types";
const SvgVector = ({ size, ...props }: IconProps) => (
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
      d="M8 2L6 4M8 2L8 9M8 2L10 4M8 9L14.0622 12.5M8 9L1.93782 12.5M14.0622 12.5L11.3301 13.232M14.0622 12.5L13.3301 9.76794M1.93782 12.5L4.66987 13.2321M1.93782 12.5L2.66987 9.76795"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgVector;
