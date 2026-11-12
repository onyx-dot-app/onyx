import type { IconProps } from "@opal/types";
const SvgArrowUpDown = ({ size, ...props }: IconProps) => (
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
      d="M13.5 5.22381L11.4714 3.19527C11.3413 3.06509 11.1707 3 11 3M8.49999 5.22392L10.5286 3.19526C10.6588 3.06509 10.8294 3 11 3M11 13V3M7.49996 10.7761L5.47141 12.8047C5.34124 12.9349 5.17062 13 5.00001 13M2.5 10.7761L4.52861 12.8047C4.65877 12.9349 4.82939 13 5.00001 13M5.00001 3L5.00001 13"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgArrowUpDown;
