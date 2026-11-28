import type { IconProps } from "@opal/types";
const SvgArrowDownDot = ({ size, ...props }: IconProps) => (
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
      d="M8.00002 14L8.00002 7.5M4.5 10.5L8.00002 14L11.5 10.5M8.00002 5C7.17158 5 6.5 4.32843 6.5 3.5C6.5 2.67157 7.17158 2 8.00002 2C8.82845 2 9.5 2.67157 9.5 3.5C9.5 4.32843 8.82845 5 8.00002 5Z"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgArrowDownDot;
