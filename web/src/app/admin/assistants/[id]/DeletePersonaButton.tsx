"use client";

import { Button } from "@/components/ui/button";
import { deletePersona } from "../lib";
import { useRouter } from "next/navigation";
import { SuccessfulPersonaUpdateRedirectType } from "../enums";

export function DeletePersonaButton({
  personaId,
  redirectType,
}: {
  personaId: number;
  redirectType: SuccessfulPersonaUpdateRedirectType;
}) {
  const router = useRouter();

  return (
    <Button
      variant="destructive"
      onClick={async () => {
        const response = await deletePersona(personaId);
        if (response.ok) {
          router.push(
            redirectType === SuccessfulPersonaUpdateRedirectType.ADMIN
              ? `/admin/assistants?u=${Date.now()}`
              : `/chat`
          );
        } else {
          alert(`Failed to delete persona - ${await response.text()}`);
        }
      }}
    >
      Delete
    </Button>
  );
}
