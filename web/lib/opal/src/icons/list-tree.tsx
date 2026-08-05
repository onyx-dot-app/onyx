import type { IconProps } from "@opal/types";

const SvgListTree = ({ size, ...props }: IconProps) => (
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
      d="M14 8H7.5M14 12H7.5M7.5 4H14M5 12H4.5C3.67157 12 3 11.3284 3 10.5V6.5M3 6.5V4.91465M3 6.5C3 7.32843 3.67157 8 4.5 8H5M3.5 5C4.32843 5 5 4.32843 5 3.5C5 2.67158 4.32842 2 3.5 2C2.67157 2 2 2.67158 2 3.5C2 4.32843 2.67157 5 3.5 5Z"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

export default SvgListTree;
