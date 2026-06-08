import type { IconProps } from "@opal/types";
const SvgBullhorn = ({ size, ...props }: IconProps) => (
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
      d="M14 4L2 6V10L4 10.3333M14 4V3M14 4V12M14 12V13M14 12L9.5 11.25M4 10.3333V12C4 12.5523 4.44772 13 5 13H8.5C9.05228 13 9.5 12.5523 9.5 12V11.25M4 10.3333L9.5 11.25"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgBullhorn;
