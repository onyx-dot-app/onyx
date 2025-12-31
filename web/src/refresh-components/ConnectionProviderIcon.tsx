import React, { memo } from "react";
import { SvgArrowExchange, SvgOnyxLogo } from "@opal/icons";

type ConnectionProviderIconProps = {
  icon: React.ReactNode;
};

const ConnectionProviderIcon = memo(({ icon }: ConnectionProviderIconProps) => {
  return (
    <div className="flex items-center gap-1">
      <div className="w-7 h-7 flex items-center justify-center">{icon}</div>
      <div className="w-4 h-4 flex items-center justify-center">
        <SvgArrowExchange className="w-3 h-3 stroke-text-04" />
      </div>
      <div className="w-7 h-7 flex items-center justify-center">
        <SvgOnyxLogo width={24} height={24} className="fill-text-04" />
      </div>
    </div>
  );
});

ConnectionProviderIcon.displayName = "ConnectionProviderIcon";

export default ConnectionProviderIcon;
