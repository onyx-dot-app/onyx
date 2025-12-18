import type { IconProps } from "@opal/types";

const SvgMinusCircle = ({ size, ...props }: IconProps) => (
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
      d="M5.33333 7.99998H10.6667M14.6667 7.99998C14.6667 11.6819 11.6819 14.6666 7.99999 14.6666C4.3181 14.6666 1.33333 11.6819 1.33333 7.99998C1.33333 4.31808 4.3181 1.33331 7.99999 1.33331C11.6819 1.33331 14.6667 4.31808 14.6667 7.99998Z"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

export default SvgMinusCircle;
