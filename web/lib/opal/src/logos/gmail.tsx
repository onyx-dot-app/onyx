import type { IconProps } from "@opal/types";
const SvgGmail = ({ size, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 52 52"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <path
      d="M5.27273 44.0007H12.9091V25.0764L2 16.7274V40.6611C2 42.509 3.46727 44.0007 5.27273 44.0007Z"
      fill="#4285F4"
    />
    <path
      d="M39.0898 44.0007H46.7262C48.5371 44.0007 49.9989 42.5035 49.9989 40.6611V16.7274L39.0898 25.0764"
      fill="#34A853"
    />
    <path
      d="M39.0898 11.2803V25.4549L49.9989 17.2773V12.9159C49.9989 8.87066 45.3789 6.56456 42.1444 8.9906"
      fill="#FBBC04"
    />
    <path
      d="M12.9094 25.455V11.2729L26.0003 21.0913L39.0912 11.2729V25.455L26.0003 35.2734"
      fill="#EA4335"
    />
    <path
      d="M2 12.9159V17.2773L12.9094 25.455L12.9091 11.2803L9.85455 8.9906C6.61455 6.56456 2 8.87066 2 12.9159Z"
      fill="#C5221F"
    />
  </svg>
);
export default SvgGmail;
