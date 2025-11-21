import SvgUser from "@/icons/user";
import React, { useRef, useState } from "react";
import Text from "@/refresh-components/texts/Text";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import Button from "@/refresh-components/buttons/Button";
import { updateUserPersonalization } from "@/lib/userSettings";
import { useUser } from "@/components/user/UserProvider";

export default function NonAdminStep() {
  const inputRef = useRef<HTMLInputElement>(null);
  const [name, setName] = useState("");
  const { refreshUser } = useUser();
  return (
    <div
      className="flex items-center justify-between w-full max-w-[800px] p-3 bg-background-tint-00 rounded-16 border border-border-01 mb-4"
      onClick={() => inputRef.current?.focus()}
      role="group"
    >
      <div className="flex items-center gap-1 h-full">
        <div className="h-full p-0.5">
          <SvgUser className="w-4 h-4 stroke-text-03" />
        </div>
        <div>
          <Text text04 mainUiAction>
            Quel nom devrait-on vous appeler ?
          </Text>
          <Text text03 secondaryBody>
            Nous afficherons ce nom dans l'application.
          </Text>
        </div>
      </div>
      <div className="flex items-center justify-end gap-2">
        <InputTypeIn
          ref={inputRef}
          placeholder="Votre nom"
          value={name || ""}
          onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
            setName(e.target.value)
          }
          className="w-[26%] min-w-40"
        />
        <Button
          disabled={name === ""}
          onClick={() => {
            updateUserPersonalization({ name })
              .then(() => {
                refreshUser();
              })
              .catch((error) => {
                console.error(error);
              });
          }}
        >
          Sauvegarder
        </Button>
      </div>
    </div>
  );
}
