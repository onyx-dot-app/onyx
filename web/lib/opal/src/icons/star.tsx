import type { IconProps } from "@opal/types";
const SvgStar = ({ size, ...props }: IconProps) => (
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
      d="M7.99999 1.33331L10.06 5.50665L14.6667 6.17998L11.3333 9.42665L12.12 14.0133L7.99999 11.8466L3.87999 14.0133L4.66666 9.42665L1.33333 6.17998L5.93999 5.50665L7.99999 1.33331Z"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgStar;
