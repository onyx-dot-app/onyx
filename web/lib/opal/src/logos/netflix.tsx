import type { IconProps } from "@opal/types";
const SvgNetflix = ({ size, ...props }: IconProps) => (
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
      d="M12.77 49.9999V1.99988C12.89 2.2999 17.7785 16.1377 22.2278 28.7409V49.2319C19.9234 49.2319 16.2877 49.3225 12.77 49.9999ZM39.2228 1.99988V49.9999L29.7651 23.288V1.99988L39.2228 1.99988Z"
      fill="url(#paint0_linear_159_1807)"
    />
    <path
      d="M22.2278 1.99988H12.77C12.89 2.2999 17.7785 16.1377 22.2278 28.7409C25.9824 39.3762 29.4243 49.1323 29.4243 49.1323C32.7144 49.1088 35.9637 49.6237 39.2228 49.9999L29.7651 23.288L22.2278 1.99988Z"
      fill="#E50914"
    />
    <defs>
      <linearGradient
        id="paint0_linear_159_1807"
        x1={32.018}
        y1={21.5599}
        x2={18.362}
        y2={26.5039}
        gradientUnits="userSpaceOnUse"
      >
        <stop stopColor="#B1060F" />
        <stop offset={0.187667} stopColor="#7B010C" />
        <stop offset={0.799356} stopColor="#7B010C" />
        <stop offset={1} stopColor="#B1060F" />
      </linearGradient>
    </defs>
  </svg>
);
export default SvgNetflix;
