export const NextcloudIcon = ({
  size = 16,
  className = "",
}: {
  size?: number;
  className?: string;
}) => {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 48 48"
      className={className}
      xmlns="http://www.w3.org/2000/svg"
    >
      {/* Official Nextcloud logo */}
      <linearGradient
        id="pOoc3r0SC5TgfojtmZvf8a"
        x1="6.378"
        x2="7.551"
        y1="16.893"
        y2="30.296"
        gradientUnits="userSpaceOnUse"
      >
        <stop offset="0" stopColor="#28afea" />
        <stop offset="1" stopColor="#0b88da" />
      </linearGradient>
      <path
        fill="url(#pOoc3r0SC5TgfojtmZvf8a)"
        d="M7,31c-3.859,0-7-3.14-7-7s3.141-7,7-7s7,3.14,7,7S10.859,31,7,31z M7,21 c-1.654,0-3,1.346-3,3s1.346,3,3,3s3-1.346,3-3S8.654,21,7,21z"
      />
      <linearGradient
        id="pOoc3r0SC5TgfojtmZvf8b"
        x1="40.39"
        x2="41.61"
        y1="17.026"
        y2="30.974"
        gradientUnits="userSpaceOnUse"
      >
        <stop offset="0" stopColor="#28afea" />
        <stop offset="1" stopColor="#0b88da" />
      </linearGradient>
      <path
        fill="url(#pOoc3r0SC5TgfojtmZvf8b)"
        d="M41,31c-3.859,0-7-3.14-7-7s3.141-7,7-7 s7,3.14,7,7S44.859,31,41,31z M41,21c-1.654,0-3,1.346-3,3s1.346,3,3,3s3-1.346,3-3S42.654,21,41,21z"
      />
      <linearGradient
        id="pOoc3r0SC5TgfojtmZvf8c"
        x1="23.041"
        x2="24.959"
        y1="13.041"
        y2="34.959"
        gradientUnits="userSpaceOnUse"
      >
        <stop offset="0" stopColor="#28afea" />
        <stop offset="1" stopColor="#0b88da" />
      </linearGradient>
      <path
        fill="url(#pOoc3r0SC5TgfojtmZvf8c)"
        d="M24,35c-6.065,0-11-4.935-11-11 s4.935-11,11-11s11,4.935,11,11S30.065,35,24,35z M24,17c-3.859,0-7,3.14-7,7s3.141,7,7,7s7-3.14,7-7S27.859,17,24,17z"
      />
    </svg>
  );
};
