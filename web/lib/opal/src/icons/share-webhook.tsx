import type { IconProps } from "@opal/types";

const SvgShareWebhook = ({ size, ...props }: IconProps) => (
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
      d="M10.0002 4C10.0002 3.99708 10.0002 3.99415 10.0001 3.99123C9.99542 2.8907 9.10181 2 8.00016 2C6.89559 2 6.00016 2.89543 6.00016 4C6.00016 4.73701 6.39882 5.38092 6.99226 5.72784L4.67276 9.70412M11.6589 13.7278C11.9549 13.9009 12.2993 14 12.6668 14C13.7714 14 14.6668 13.1046 14.6668 12C14.6668 10.8954 13.7714 10 12.6668 10C12.2993 10 11.9549 10.0991 11.6589 10.2722L9.33943 6.29588M2.33316 10.2678C1.73555 10.6136 1.3335 11.2599 1.3335 12C1.3335 13.1046 2.22893 14 3.3335 14C4.43807 14 5.3335 13.1046 5.3335 12H10.0002"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgShareWebhook;
