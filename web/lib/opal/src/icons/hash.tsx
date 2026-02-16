import type { IconProps } from "@opal/types";
const SvgHash = ({ size, ...props }: IconProps) => (
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
      d="M2.66667 6H13.3333M2.66667 10H13.3333M6.66667 2L5.33334 14M10.6667 2L9.33334 14"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgHash;
