// Per-provider component so each owns its own mutation.
import { router } from "expo-router";
import { View } from "react-native";

import { BrowserSsoCancelledError } from "@/api/auth/browserSso";
import type { ProviderDescriptor, ProviderId } from "@/api/auth/providers";
import { useBrowserLogin } from "@/api/auth/useBrowserLogin";
import { InputErrorText } from "@/components/form";
import { Button } from "@/components/ui/button";
import SvgGoogle from "@/icons/google";
import type { IconFunctionComponent } from "@/icons/types";

const ICON_BY_PROVIDER: Partial<Record<ProviderId, IconFunctionComponent>> = {
  google: SvgGoogle,
};

interface ProviderSsoButtonProps {
  provider: ProviderDescriptor;
}

export function ProviderSsoButton({ provider }: ProviderSsoButtonProps) {
  const mutation = useBrowserLogin();

  // A cancel isn't a failure — stay quiet on it.
  const showError =
    mutation.isError && !(mutation.error instanceof BrowserSsoCancelledError);

  return (
    <View>
      <Button
        variant="default"
        prominence="secondary"
        width="full"
        icon={ICON_BY_PROVIDER[provider.id]}
        loading={mutation.isPending}
        onPress={() =>
          mutation.mutate(provider, {
            onSuccess: () => router.replace("/"),
          })
        }
      >
        {`Continue with ${provider.label}`}
      </Button>
      {showError ? (
        <View className="mt-12">
          <InputErrorText>
            {`Couldn't sign in with ${provider.label}. Please try again.`}
          </InputErrorText>
        </View>
      ) : null}
    </View>
  );
}
