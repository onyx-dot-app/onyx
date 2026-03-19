import type { IconProps } from "@opal/types";
const SvgUserShield = ({ size, ...props }: IconProps) => (
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
      d="M1 14C1 13.6667 1 13.3333 1 13C1 11.3431 2.34316 10 4.00002 10H7M8.75 4.75C8.75 6.26878 7.51878 7.5 6 7.5C4.48122 7.5 3.25 6.26878 3.25 4.75C3.25 3.23122 4.48122 2 6 2C7.51878 2 8.75 3.23122 8.75 4.75ZM12 14.5C12 14.5 14.5 13.25 14.5 11.375V9L12 8L9.5 9V11.375C9.5 13.25 12 14.5 12 14.5Z"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgUserShield;
