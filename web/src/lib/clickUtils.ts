import { AppRouterInstance } from "next/dist/shared/lib/app-router-context.shared-runtime";
import { MouseEventHandler } from "react";

export function buildRedirectClickHandler(
  url: string,
  router?: AppRouterInstance
) {
  const redirectHandler: MouseEventHandler = (event) => {
    if (event.button === 1 || event.shiftKey) {
      window.open(url, "_blank");
    }

    if (router) {
      router.push(url);
    } else {
      window.open(url);
    }
  };
  return redirectHandler;
}
