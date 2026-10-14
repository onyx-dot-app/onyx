import type { IconProps } from "@opal/types";
const SvgScissors = ({ size, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 12 12"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    stroke="currentColor"
    {...props}
  >
    <path
      d="M10 2L6 6M7.235 7.24L10 10M6 6L4.06066 4.06066M6 6L4.06066 7.93934M4.06066 4.06066C4.33211 3.78921 4.5 3.41421 4.5 3C4.5 2.17157 3.82843 1.5 3 1.5C2.17157 1.5 1.5 2.17157 1.5 3C1.5 3.82843 2.17157 4.5 3 4.5C3.41421 4.5 3.78921 4.33211 4.06066 4.06066ZM4.06066 7.93934C3.78921 7.66789 3.41421 7.5 3 7.5C2.17157 7.5 1.5 8.17157 1.5 9C1.5 9.82843 2.17157 10.5 3 10.5C3.82843 10.5 4.5 9.82843 4.5 9C4.5 8.58579 4.33211 8.21079 4.06066 7.93934Z"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgScissors;
