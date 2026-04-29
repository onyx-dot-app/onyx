import type { IconProps } from "@opal/types";
const SvgCheckAll = ({ size, ...props }: IconProps) => (
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
      d="M11.8333 4L8.49999 7.33334M4.5 11.3333L1.5 8.33334M5.16666 7.99996L8.49999 11.3333L14.5 5.33329"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgCheckAll;
