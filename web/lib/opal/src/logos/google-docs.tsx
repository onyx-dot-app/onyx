import type { IconProps } from "@opal/types";
const SvgGoogleDocs = ({ size, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 52 52"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <path
      d="M32.5 2H13C11.3431 2 10 3.34315 10 5V47C10 48.6569 11.3431 50 13 50H39C40.6569 50 42 48.6569 42 47V11.5L32.5 2Z"
      fill="#4285F4"
    />
    <path d="M32.5 2L42 11.5H32.5V2Z" fill="#A1C2FA" />
    <path
      d="M17 25.5H35V28.5H17V25.5ZM17 31.5H35V34.5H17V31.5ZM17 37.5H29.5V40.5H17V37.5Z"
      fill="white"
    />
  </svg>
);
export default SvgGoogleDocs;
