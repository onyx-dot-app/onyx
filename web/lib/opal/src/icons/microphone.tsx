import type { IconProps } from "@opal/types";

const SvgMicrophone = ({ size, ...props }: IconProps) => (
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
      d="M12.5 7V7.5C12.5 9.98528 10.4853 12 8 12M3.5 7V7.5C3.5 9.98528 5.51472 12 8 12M8 12V14.5M8 14.5H5M8 14.5H11M8 9.5C6.89543 9.5 6 8.60457 6 7.5V3.5C6 2.39543 6.89543 1.5 8 1.5C9.10457 1.5 10 2.39543 10 3.5V7.5C10 8.60457 9.10457 9.5 8 9.5Z"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgMicrophone;
