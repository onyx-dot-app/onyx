import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import useSWR, { SWRConfig, useSWRConfig } from "swr";
import {
  refreshSkillLists,
  refreshSkillListsChecked,
} from "@/lib/skills/cache";
import { SWR_KEYS } from "@/lib/swr-keys";

function wrapper({ children }: { children: ReactNode }) {
  return (
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      {children}
    </SWRConfig>
  );
}

function useLists(fetcher: (key: string) => Promise<unknown>) {
  useSWR(SWR_KEYS.userSkills, fetcher);
  useSWR(SWR_KEYS.chatSkills, fetcher);
  return useSWRConfig();
}

test("a failed list fetch makes the checked refresh report false", async () => {
  let fail = false;
  const fetcher = async (key: string) => {
    if (fail && key === SWR_KEYS.chatSkills) throw new Error("down");
    return [];
  };
  const { result } = renderHook(() => useLists(fetcher), { wrapper });
  await waitFor(() =>
    expect(result.current.cache.get(SWR_KEYS.chatSkills)?.data).toEqual([])
  );

  expect(
    await refreshSkillListsChecked(result.current.mutate, result.current.cache)
  ).toBe(true);
  fail = true;
  // SWR keeps the failure in the key's error, so the plain refresh resolves.
  await expect(refreshSkillLists(result.current.mutate)).resolves.toBe(
    undefined
  );
  expect(
    await refreshSkillListsChecked(result.current.mutate, result.current.cache)
  ).toBe(false);
});
