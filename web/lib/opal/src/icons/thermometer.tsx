import type { IconProps } from "@opal/types";

const SvgThermometer = ({ size, ...props }: IconProps) => (
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
      d="M8 1C8.9078 1 9.6667 1.7589 9.6667 2.6667L9.6667 8.4215C10.7586 9.0139 11.5 10.1704 11.5 11.5C11.5 13.433 9.933 15 8 15C6.067 15 4.5 13.433 4.5 11.5C4.5 10.1704 5.2414 9.0139 6.3333 8.4215L6.3333 2.6667C6.3333 1.7589 7.0922 1 8 1Z"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgThermometer;
