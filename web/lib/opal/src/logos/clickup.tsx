import type { IconProps } from "@opal/types";
const SvgClickup = ({ size, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 52 52"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <path
      fillRule="evenodd"
      clipRule="evenodd"
      d="M8.90418 38.0156C8.48521 37.5048 8.57687 36.7529 9.09202 36.3393L13.9722 32.421C14.3979 32.0792 15.0202 32.1564 15.3673 32.5777C18.6821 36.602 22.1995 38.465 26.0929 38.465C29.9593 38.465 33.3808 36.6284 36.5504 32.6487C36.8906 32.2216 37.5114 32.1333 37.9432 32.4675L42.8901 36.2958C43.4125 36.7001 43.5177 37.45 43.1075 37.9678C38.4211 43.8833 32.6832 47 26.0929 47C19.5217 47 13.7326 43.9027 8.90418 38.0156Z"
      fill="url(#paint0_linear_8_600)"
    />
    <path
      fillRule="evenodd"
      clipRule="evenodd"
      d="M26.3291 15.9283C26.1451 15.7654 25.8686 15.7653 25.6845 15.9281L15.073 25.3113C14.6673 25.67 14.0468 25.6283 13.6927 25.2187L9.5539 20.43C9.20474 20.0261 9.2465 19.4162 9.64747 19.0635L25.3644 5.24225C25.7318 4.91918 26.282 4.91926 26.6493 5.24243L42.3697 19.0742C42.7709 19.4271 42.8122 20.0377 42.4622 20.4415L38.3134 25.2277C37.9588 25.6367 37.3387 25.6776 36.9335 25.3189L26.3291 15.9283Z"
      fill="url(#paint1_linear_8_600)"
    />
    <defs>
      <linearGradient
        id="paint0_linear_8_600"
        x1={8.16539}
        y1={25.9471}
        x2={43.8296}
        y2={25.9471}
        gradientUnits="userSpaceOnUse"
      >
        <stop offset={0.225962} stopColor="#6647F0" />
        <stop offset={0.793269} stopColor="#0091FF" />
      </linearGradient>
      <linearGradient
        id="paint1_linear_8_600"
        x1={8.16538}
        y1={25.6009}
        x2={43.8296}
        y2={25.6009}
        gradientUnits="userSpaceOnUse"
      >
        <stop stopColor="#FF02F0" />
        <stop offset={0.778846} stopColor="#F76808" />
      </linearGradient>
    </defs>
  </svg>
);
export default SvgClickup;
