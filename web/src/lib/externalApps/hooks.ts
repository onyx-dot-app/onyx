"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import isEqual from "lodash/isEqual";
import type { ExternalAppAdminResponse } from "@/app/craft/v1/apps/registry";

export function useSyncedAssociatedSkillIds(
  app: ExternalAppAdminResponse | null
) {
  const persistedSkillIds = useMemo(
    () => app?.associated_skills.map((skill) => skill.id) ?? [],
    [app?.associated_skills]
  );
  const previousPersistedSkillIds = useRef(persistedSkillIds);
  const [selectedSkillIds, setSelectedSkillIds] = useState(persistedSkillIds);

  useEffect(() => {
    const previous = previousPersistedSkillIds.current;
    previousPersistedSkillIds.current = persistedSkillIds;
    setSelectedSkillIds((current) =>
      isEqual(new Set(current), new Set(previous)) ? persistedSkillIds : current
    );
  }, [persistedSkillIds]);

  return [selectedSkillIds, setSelectedSkillIds] as const;
}
