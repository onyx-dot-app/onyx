import type { IconProps } from "@opal/types";
const SvgFilePlus = ({ size, ...props }: IconProps) => (
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
      d="M13.33333 5.33333L9.33333 1.33333H4C3.27377 1.33333 2.66667 1.94044 2.66667 2.66667V13.33333C2.66667 14.0596 3.27377 14.66667 4 14.66667H12C12.72623 14.66667 13.33333 14.0596 13.33333 13.33333V5.33333ZM9.33333 1.33333L9.33333 5.33333L13.33333 5.33333M8 12V8M6 10H10"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgFilePlus;
