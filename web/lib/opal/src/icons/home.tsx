import type { IconProps } from "@opal/types";
const SvgHome = ({ size, ...props }: IconProps) => (
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
      d="M6 14.6667V8H10V14.6667M2 6L8 1.33333L14 6V13.3333C14 13.6869 13.8595 14.0261 13.6095 14.2761C13.3595 14.5262 13.0203 14.6667 12.6667 14.6667H3.33333C2.97971 14.6667 2.64057 14.5262 2.39052 14.2761C2.14048 14.0261 2 13.6869 2 13.3333V6Z"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgHome;
