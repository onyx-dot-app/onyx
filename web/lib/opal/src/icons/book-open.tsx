import type { IconProps } from "@opal/types";

const SvgBookOpen = ({ size, ...props }: IconProps) => (
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
      d="M7.99999 4.66667C7.99999 3.95942 7.71904 3.28115 7.21895 2.78105C6.71885 2.28095 6.04057 2 5.33333 2H1.33333V12H5.99999C6.53043 12 7.03914 12.2107 7.41421 12.5858C7.78928 12.9609 7.99999 13.4696 7.99999 14M7.99999 4.66667V14M7.99999 4.66667C7.99999 3.95942 8.28095 3.28115 8.78104 2.78105C9.28114 2.28095 9.95942 2 10.6667 2H14.6667V12H9.99999C9.46956 12 8.96085 12.2107 8.58578 12.5858C8.21071 12.9609 7.99999 13.4696 7.99999 14"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgBookOpen;
