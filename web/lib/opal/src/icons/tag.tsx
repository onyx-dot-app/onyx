import type { IconProps } from "@opal/types";
const SvgTag = ({ size, ...props }: IconProps) => (
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
      d="M4.66666 4.66668H4.67333M13.7267 8.94001L8.94666 13.72C8.82283 13.844 8.67578 13.9423 8.51392 14.0094C8.35205 14.0765 8.17855 14.1111 8.00333 14.1111C7.82811 14.1111 7.65461 14.0765 7.49274 14.0094C7.33088 13.9423 7.18383 13.844 7.05999 13.72L1.33333 8.00001V1.33334H7.99999L13.7267 7.06001C13.975 7.30983 14.1144 7.64776 14.1144 8.00001C14.1144 8.35226 13.975 8.69019 13.7267 8.94001Z"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgTag;
