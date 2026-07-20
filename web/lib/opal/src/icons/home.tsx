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
      d="M2 6.66667L8 2L14 6.66667V13.3333C14 13.7015 13.7015 14 13.3333 14H10.6667V9.33333H5.33333V14H2.66667C2.29848 14 2 13.7015 2 13.3333V6.66667Z"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgHome;
