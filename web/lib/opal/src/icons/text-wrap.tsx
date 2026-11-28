import type { IconProps } from "@opal/types";
const SvgTextWrap = ({ size, ...props }: IconProps) => (
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
      d="M2 3.5h12M2 7.5h9.5a2.5 2.5 0 0 1 0 5H8m2-2-2 2 2 2M2 12.5h3"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgTextWrap;
