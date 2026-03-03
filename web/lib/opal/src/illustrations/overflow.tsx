import type { IconProps } from "@opal/types";
const SvgOverflow = ({ size, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 120 120"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    stroke="currentColor"
    {...props}
  >
    <path
      d="M22.5 71.2501L25.3301 91.0607C25.8579 94.7555 29.0223 97.5 32.7547 97.5H87.2453C90.9777 97.5 94.1421 94.7555 94.6699 91.0607L97.5 71.2501H22.5Z"
      fill="#E6E6E6"
      strokeWidth={3.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
    <path
      d="M18.7501 46.8752L78.5183 52.4717M32.7965 34.583L91.8752 45.0002M45.1839 22.5002L103.125 38.0255M90.0002 61.8752H30.0002"
      strokeWidth={3.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgOverflow;
