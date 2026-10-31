import type { IconProps } from "@opal/types";
const SvgUsers = ({ size, ...props }: IconProps) => (
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
      d="M11 14V13C11 11.3431 9.65686 9.99999 8 10H4.00002C2.34316 9.99999 1 11.3431 1 13V14M15 14V13C15 11.5135 13.9188 10.238 12.5 10M10.5 7.5C11.7801 7.26487 12.75 6.09803 12.75 4.75C12.75 3.40197 11.7801 2.23513 10.5 2M8.75 4.75C8.75 6.26878 7.51878 7.5 6 7.5C4.48122 7.5 3.25 6.26878 3.25 4.75C3.25 3.23122 4.48122 2 6 2C7.51878 2 8.75 3.23122 8.75 4.75Z"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgUsers;
