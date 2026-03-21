"use client";

import { errorHandlingFetcher, RedirectError } from "@/lib/fetcher";
import useSWR from "swr";
import Modal from "@/refresh-components/Modal";
import { useCallback, useEffect, useRef, useState } from "react";
import { getSecondsUntilExpiration } from "@/lib/time";
import { refreshToken, logout } from "@/lib/user";
import { NEXT_PUBLIC_CUSTOM_REFRESH_URL } from "@/lib/constants";
import { Button } from "@opal/components";
import { usePathname, useRouter } from "next/navigation";
import { SvgAlertTriangle, SvgLogOut } from "@opal/icons";
import { Content } from "@opal/layouts";
import { useCurrentUser } from "@/hooks/useCurrentUser";
import { getExtensionContext } from "@/lib/extension/utils";

const PUBLIC_PATHS = new Set(["/", "/login", "/register"]);
const PUBLIC_PATH_PREFIXES = ["/auth", "/anonymous"];

function isPublicPath(pathname: string | null): boolean {
  if (!pathname) {
    return false;
  }

  if (PUBLIC_PATHS.has(pathname)) {
    return true;
  }

  return PUBLIC_PATH_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`)
  );
}

export default function AppHealthBanner() {
  const router = useRouter();
  const { error } = useSWR("/api/health", errorHandlingFetcher);
  const [expired, setExpired] = useState(false);
  const [showLoggedOutModal, setShowLoggedOutModal] = useState(false);
  const pathname = usePathname();
  const isPublicPathname = isPublicPath(pathname);
  const expirationTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const refreshIntervalRef = useRef<NodeJS.Timer | null>(null);

  const { user, mutateUser, userError } = useCurrentUser();

  useEffect(() => {
    if (userError?.status !== 403) {
      return;
    }

    let isActive = true;

    void (async () => {
      try {
        await logout();
      } finally {
        if (isActive && !isPublicPathname) {
          setShowLoggedOutModal(true);
        }
      }
    })();

    return () => {
      isActive = false;
    };
  }, [userError, isPublicPathname]);

  useEffect(() => {
    if (!(error instanceof RedirectError) && !expired) {
      return;
    }

    if (!isPublicPathname) {
      setShowLoggedOutModal(true);
    }
  }, [error, expired, isPublicPathname]);

  function handleLogin() {
    setShowLoggedOutModal(false);
    const { isExtension } = getExtensionContext();
    if (isExtension) {
      window.open(
        window.location.origin + "/auth/login",
        "_blank",
        "noopener,noreferrer"
      );
    } else {
      router.push("/auth/login");
    }
  }

  const setupExpirationTimeout = useCallback(
    (secondsUntilExpiration: number) => {
      if (expirationTimeoutRef.current) {
        clearTimeout(expirationTimeoutRef.current);
      }

      const timeUntilExpire = (secondsUntilExpiration + 10) * 1000;
      expirationTimeoutRef.current = setTimeout(() => {
        setExpired(true);

        if (!isPublicPathname) {
          setShowLoggedOutModal(true);
        }
      }, timeUntilExpire);
    },
    [isPublicPathname]
  );

  useEffect(() => {
    return () => {
      if (expirationTimeoutRef.current) {
        clearTimeout(expirationTimeoutRef.current);
      }

      if (refreshIntervalRef.current) {
        clearInterval(refreshIntervalRef.current);
      }
    };
  }, []);

  useEffect(() => {
    if (!user) {
      return;
    }

    const secondsUntilExpiration = getSecondsUntilExpiration(user);
    if (secondsUntilExpiration === null) {
      return;
    }

    setupExpirationTimeout(secondsUntilExpiration);

    if (NEXT_PUBLIC_CUSTOM_REFRESH_URL) {
      const refreshUrl = NEXT_PUBLIC_CUSTOM_REFRESH_URL;

      const attemptTokenRefresh = async () => {
        let retryCount = 0;
        const maxRetries = 3;

        while (retryCount < maxRetries) {
          try {
            const refreshTokenData = await refreshToken(refreshUrl);
            if (!refreshTokenData) {
              throw new Error("Failed to refresh token");
            }

            const response = await fetch(
              "/api/enterprise-settings/refresh-token",
              {
                method: "POST",
                headers: {
                  "Content-Type": "application/json",
                },
                body: JSON.stringify(refreshTokenData),
              }
            );
            if (!response.ok) {
              throw new Error(`HTTP error! status: ${response.status}`);
            }

            await new Promise((resolve) => setTimeout(resolve, 4000));

            const updatedUser = await mutateUser();

            if (updatedUser) {
              const newSecondsUntilExpiration =
                getSecondsUntilExpiration(updatedUser);
              if (newSecondsUntilExpiration !== null) {
                setupExpirationTimeout(newSecondsUntilExpiration);
                console.debug(
                  `Token refreshed, new expiration in ${newSecondsUntilExpiration} seconds`
                );
              }
            }

            break;
          } catch (error) {
            console.error(
              `Error refreshing token (attempt ${
                retryCount + 1
              }/${maxRetries}):`,
              error
            );
            retryCount++;

            if (retryCount === maxRetries) {
              console.error("Max retry attempts reached");
            } else {
              await new Promise((resolve) =>
                setTimeout(resolve, Math.pow(2, retryCount) * 1000)
              );
            }
          }
        }
      };

      const refreshInterval = 60 * 15;

      if (refreshIntervalRef.current) {
        clearInterval(refreshIntervalRef.current);
      }

      refreshIntervalRef.current = setInterval(
        attemptTokenRefresh,
        refreshInterval * 1000
      );

      if (secondsUntilExpiration < refreshInterval) {
        void attemptTokenRefresh();
      }
    }
  }, [user, setupExpirationTimeout, mutateUser]);

  if (showLoggedOutModal) {
    return (
      <Modal open>
        <Modal.Content width="sm" height="sm">
          <Modal.Header icon={SvgLogOut} title="Tu sesi\u00f3n ha finalizado" />
          <Modal.Body>
            <p className="text-sm">
              Tu sesi\u00f3n expir\u00f3. Inicia sesi\u00f3n de nuevo para
              continuar.
            </p>
          </Modal.Body>
          <Modal.Footer>
            <Button onClick={handleLogin}>Iniciar sesi\u00f3n</Button>
          </Modal.Footer>
        </Modal.Content>
      </Modal>
    );
  }

  if (!error && !expired) {
    return null;
  }

  if (error instanceof RedirectError || expired) {
    return null;
  }

  return (
    <div className="fixed top-0 left-0 z-[101] w-full bg-status-error-01 p-3">
      <Content
        icon={SvgAlertTriangle}
        title="El backend no est\u00e1 disponible en este momento"
        description="Si es tu configuraci\u00f3n inicial o acabas de actualizar el despliegue, es probable que el backend todav\u00eda se est\u00e9 iniciando. Espera uno o dos minutos y luego recarga la p\u00e1gina. Si el problema contin\u00faa, revisa la configuraci\u00f3n del backend o contacta a un administrador."
        sizePreset="main-content"
        variant="section"
      />
    </div>
  );
}
