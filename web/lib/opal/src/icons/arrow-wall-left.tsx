import type { IconProps } from "@opal/types";

const SvgArrowWallLeft = ({ size, ...props }: IconProps) => (
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
      d="M6.55719 5.16667L4.19527 7.5286C4.06509 7.65877 4 7.82938 4 8M6.55719 10.8333L4.19526 8.4714C4.06509 8.34123 4 8.17062 4 8M14 8H4M1 3.16669V12.8334"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

export default SvgArrowWallLeft;
