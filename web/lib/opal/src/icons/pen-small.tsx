import type { IconProps } from "@opal/types";
const SvgPenSmall = ({ size, ...props }: IconProps) => (
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
      d="M6.5 11L11.5 6L10 4.5L5 9.5L5 11H6.5Z"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgPenSmall;
