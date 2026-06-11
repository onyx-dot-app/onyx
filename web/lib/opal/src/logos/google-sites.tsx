import type { IconProps } from "@opal/types";
const SvgGoogleSites = ({ size, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 52 52"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <path d="M31.2316 14.5H42.73L31.2316 3V14.5Z" fill="#354287" />
    <path
      fillRule="evenodd"
      clipRule="evenodd"
      d="M42.73 14.5H31.2316V3H12.4159C10.6833 3 9.28 4.40352 9.28 6.13636V45.8636C9.28 47.5965 10.6833 49 12.4159 49H39.5941C41.3267 49 42.73 47.5965 42.73 45.8636V14.5ZM16.5972 34.8864H30.1862V26H16.5972V34.8864ZM32.7995 34.8864H35.4128V26H32.7995V34.8864ZM16.5972 23.3864H35.4128V20.7727H16.5972V23.3864Z"
      fill="#4758B5"
    />
    <path d="M30.1862 34.8864H16.5972V26H30.1862V34.8864Z" fill="white" />
    <path d="M35.4128 23.3864H16.5972V20.7727H35.4128V23.3864Z" fill="white" />
    <path d="M35.4128 34.8864H32.7995V26H35.4128V34.8864Z" fill="white" />
  </svg>
);
export default SvgGoogleSites;
