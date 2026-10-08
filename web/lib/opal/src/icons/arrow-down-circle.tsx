import type { IconProps } from "@opal/types";

const SvgArrowDownCircle = ({ size, ...props }: IconProps) => (
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
      d="M5.33333 8L8 10.6667L10.6667 8M8 10.6667L8 5.33331M8 14.6667C11.6819 14.6667 14.6667 11.6819 14.6667 8C14.6667 4.31808 11.6819 1.33331 8 1.33331C4.31809 1.33331 1.33333 4.31808 1.33333 8C1.33333 11.6819 4.31809 14.6667 8 14.6667Z"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgArrowDownCircle;
