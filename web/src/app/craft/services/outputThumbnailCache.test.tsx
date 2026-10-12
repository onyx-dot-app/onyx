import { useState } from "react";
import { renderHook, waitFor } from "@tests/setup/test-utils";
import { SWRConfig } from "swr";
import { useFilePreview } from "@/lib/build/hooks";
import {
  OutputThumbnailCache,
  readOutputThumbnailCache,
  retainOutputThumbnailCache,
} from "@/app/craft/services/outputThumbnailCache";

function thumbnail(content: string) {
  return {
    data: {
      identity: "thumbnail-v1",
      data: { content, mimeType: "image/jpeg" },
    },
  };
}

// Retained payload budgets.
it("evicts the least recently written entry without mutating cache reads", () => {
  const cache = new OutputThumbnailCache(2);
  cache.set("first", thumbnail("first"));
  cache.set("second", thumbnail("second"));
  cache.get("first");
  cache.set("third", thumbnail("third"));
  expect([...cache.keys()]).toEqual(["second", "third"]);
});

it("bounds retained strings and releases accounting on replacement and clear", () => {
  const cache = new OutputThumbnailCache(10, 100);
  cache.set("first", thumbnail("a".repeat(60)));
  cache.set("second", thumbnail("b".repeat(60)));
  expect([...cache.keys()]).toEqual(["second"]);
  cache.set("second", thumbnail("small"));
  cache.set("third", thumbnail("small"));
  expect(cache.size).toBe(2);
  cache.clear();
  cache.set("fourth", thumbnail("c".repeat(70)));
  expect(cache.size).toBe(1);
});

it("releases the retained payload budget when a terminal failure replaces bytes", () => {
  const cache = new OutputThumbnailCache(10, 100);
  cache.set("first", thumbnail("a".repeat(90)));
  cache.set("first", {
    data: { identity: "thumbnail-v1", error: new Error("Forbidden") },
  });
  cache.set("second", thumbnail("b".repeat(90)));
  expect([...cache.keys()]).toEqual(["first", "second"]);
});

// Stable SWR scope across tile mounts.
it("reuses cached thumbnail bytes immediately after remount", async () => {
  const cache = new OutputThumbnailCache();
  const payload = { content: "image bytes", mimeType: "image/jpeg" };
  const load = jest.fn().mockResolvedValue(payload);
  function Wrapper({ children }: { children: React.ReactNode }) {
    const [provider] = useState(() => cache.createProvider());
    return (
      <SWRConfig value={{ provider: () => provider }}>{children}</SWRConfig>
    );
  }
  const first = renderHook(
    () => useFilePreview("thumbnail", load, { revision: "v1" }),
    { wrapper: Wrapper }
  );
  await waitFor(() => expect(first.result.current.data).toBe(payload));
  first.unmount();
  const second = renderHook(
    () => useFilePreview("thumbnail", load, { revision: "v1" }),
    { wrapper: Wrapper }
  );
  expect(second.result.current.data).toBe(payload);
  expect(load).toHaveBeenCalledTimes(1);
});

// Persistent previews never provide an inventory or authorize a file fetch.
const savedKey = "craft-output-thumbnail:session:outputs/image.png";
function savedThumbnail(
  revision = "v1",
  content = "data:image/png;base64,aGVsbG8="
) {
  return {
    data: {
      identity: JSON.stringify([savedKey, revision, 0]),
      data: { content, mimeType: "image/png", isImage: true },
    },
  };
}
const storageKey = "onyx:craft:output-thumbnails:v1:owner";
beforeEach(() => window.sessionStorage.clear());

it("restores successful revision-tagged previews across a browser reload", () => {
  new OutputThumbnailCache(128, 100000, "owner").set(
    savedKey,
    savedThumbnail()
  );
  const restored = new OutputThumbnailCache(128, 100000, "owner");
  expect(restored.get(savedKey)?.data).toEqual(savedThumbnail().data);
  expect(
    new OutputThumbnailCache(128, 100000, "another-owner").get(savedKey)
  ).toBeUndefined();
});

it("does not persist unversioned or failed responses", () => {
  const cache = new OutputThumbnailCache(128, 100000, "owner");
  cache.set(savedKey, {
    data: {
      identity: JSON.stringify([savedKey, null, 0]),
      data: { content: "bytes", mimeType: "image/png" },
    },
  });
  expect(new OutputThumbnailCache(128, 100000, "owner").size).toBe(0);
  cache.set(savedKey, savedThumbnail());
  cache.set(savedKey, {
    data: {
      identity: savedThumbnail().data.identity,
      error: new Error("Forbidden"),
    },
  });
  expect(new OutputThumbnailCache(128, 100000, "owner").size).toBe(0);
});

it("rejects corrupt storage and expired previews", () => {
  window.sessionStorage.setItem(storageKey, "broken JSON");
  expect(new OutputThumbnailCache(128, 100000, "owner").size).toBe(0);
  window.sessionStorage.setItem(
    storageKey,
    JSON.stringify([
      {
        key: savedKey,
        savedAt: Date.now() - 31 * 60 * 1000,
        data: savedThumbnail().data,
      },
      {
        key: savedKey,
        savedAt: Date.now(),
        data: { ...savedThumbnail().data, identity: "malformed" },
      },
    ])
  );
  expect(new OutputThumbnailCache(128, 100000, "owner").size).toBe(0);
});

it("persists eviction and session purges", () => {
  const cache = new OutputThumbnailCache(1, 100000, "owner");
  cache.set(savedKey, savedThumbnail());
  const another = "craft-output-thumbnail:other:outputs/image.png";
  cache.set(another, {
    data: {
      ...savedThumbnail().data,
      identity: JSON.stringify([another, "v1", 0]),
    },
  });
  expect([...new OutputThumbnailCache(128, 100000, "owner").keys()]).toEqual([
    another,
  ]);
  cache.clearSession("other");
  expect(new OutputThumbnailCache(128, 100000, "owner").size).toBe(0);
});

it("removes deleted or changed revisions only in the reconciled session", () => {
  const cache = new OutputThumbnailCache(128, 100000, "owner");
  cache.set(savedKey, savedThumbnail());
  cache.reconcileSession("different", {});
  expect(cache.size).toBe(1);
  cache.reconcileSession("session", {
    "outputs/image.png": {
      path: "outputs/image.png",
      revision: "v2",
      size: 10,
    },
  });
  expect(cache.size).toBe(0);
  expect(new OutputThumbnailCache(128, 100000, "owner").size).toBe(0);
  cache.set(savedKey, savedThumbnail());
  expect(cache.size).toBe(0);
  cache.reconcileSession("session", {});
  cache.set(savedKey, savedThumbnail());
  expect(cache.size).toBe(0);
});

it("bounds serialized storage including metadata", () => {
  const cache = new OutputThumbnailCache(128, 16 * 1024 * 1024, "owner");
  for (let index = 0; index < 12; index++) {
    const key = `craft-output-thumbnail:session:outputs/${index}.png`;
    cache.set(key, {
      data: {
        identity: JSON.stringify([key, "v1", 0]),
        data: { content: "x".repeat(250000), mimeType: "image/png" },
      },
    });
  }
  expect(window.sessionStorage.getItem(storageKey)?.length).toBeLessThanOrEqual(
    2 * 1024 * 1024
  );
  expect(
    new OutputThumbnailCache(128, 16 * 1024 * 1024, "owner").size
  ).toBeLessThan(12);
});

it("rejects late responses after terminal purge until a new inventory is accepted", () => {
  const cache = new OutputThumbnailCache(128, 100000, "owner");
  cache.clearSession("session");
  cache.set(savedKey, savedThumbnail());
  expect(cache.size).toBe(0);
  expect(new OutputThumbnailCache(128, 100000, "owner").size).toBe(0);
  cache.reconcileSession("session", {
    "outputs/image.png": {
      path: "outputs/image.png",
      revision: "v2",
      size: 10,
    },
  });
  cache.set(savedKey, savedThumbnail("v1"));
  expect(cache.size).toBe(0);
  cache.set(savedKey, savedThumbnail("v2"));
  expect(cache.size).toBe(1);
});

it("does not serialize metadata updates and batches session removals", () => {
  const cache = new OutputThumbnailCache(128, 100000, "owner");
  const write = jest.spyOn(Storage.prototype, "setItem");
  try {
    cache.set(savedKey, savedThumbnail());
    write.mockClear();
    cache.set(savedKey, { ...savedThumbnail(), isValidating: true });
    cache.set(savedKey, { ...savedThumbnail(), isValidating: false });
    expect(write).not.toHaveBeenCalled();
    const another = "craft-output-thumbnail:session:outputs/other.png";
    cache.set(another, {
      data: {
        ...savedThumbnail().data,
        identity: JSON.stringify([another, "v1", 0]),
      },
    });
    write.mockClear();
    cache.clearSession("session");
    expect(write).toHaveBeenCalledTimes(1);
  } finally {
    write.mockRestore();
  }
});

it("retires previous user caches so late writes cannot replace newer saved bytes", () => {
  const previous = new OutputThumbnailCache(128, 100000, "switch-owner");
  retainOutputThumbnailCache("switch-owner", previous);
  previous.set(savedKey, savedThumbnail("v1"));
  retainOutputThumbnailCache("another-owner", new OutputThumbnailCache());
  const current = new OutputThumbnailCache(128, 100000, "switch-owner");
  retainOutputThumbnailCache("switch-owner", current);
  current.set(savedKey, savedThumbnail("v2"));
  previous.set(savedKey, savedThumbnail("v1"));
  expect(
    new OutputThumbnailCache(128, 100000, "switch-owner").get(savedKey)?.data
      ?.identity
  ).toBe(savedThumbnail("v2").data.identity);
  expect(previous.size).toBe(0);
});

it("resets anonymous bytes on authentication transitions", () => {
  const previous = new OutputThumbnailCache();
  retainOutputThumbnailCache(undefined, previous);
  previous.set(savedKey, savedThumbnail());
  retainOutputThumbnailCache("authenticated-owner", new OutputThumbnailCache());
  const current = new OutputThumbnailCache();
  retainOutputThumbnailCache(undefined, current);
  previous.set(savedKey, savedThumbnail());
  expect(current.size).toBe(0);
  expect(previous.size).toBe(0);
});

it("rejects late previous-session writes while retaining its accepted cached bytes", () => {
  const cache = new OutputThumbnailCache(128, 100000, "owner");
  cache.activateSession("session");
  cache.set(savedKey, savedThumbnail("v1"));
  cache.activateSession("other");
  cache.set(savedKey, savedThumbnail("v2"));
  expect(cache.get(savedKey)?.data?.identity).toBe(
    savedThumbnail("v1").data.identity
  );
  const otherKey = "craft-output-thumbnail:other:outputs/image.png";
  cache.set(otherKey, {
    data: {
      ...savedThumbnail().data,
      identity: JSON.stringify([otherKey, "v1", 0]),
    },
  });
  expect(cache.has(otherKey)).toBe(true);
  cache.activateSession(null);
  cache.set(otherKey, {
    data: {
      ...savedThumbnail().data,
      identity: JSON.stringify([otherKey, "v2", 0]),
    },
  });
  expect(cache.get(otherKey)?.data?.identity).toBe(
    JSON.stringify([otherKey, "v1", 0])
  );
});

it("accepts partial revisions without deleting unseen cached files", () => {
  const cache = new OutputThumbnailCache(128, 100000, "owner");
  cache.set(savedKey, savedThumbnail());
  const otherKey = "craft-output-thumbnail:session:outputs/other.png";
  cache.set(otherKey, {
    data: {
      ...savedThumbnail().data,
      identity: JSON.stringify([otherKey, "v1", 0]),
    },
  });
  cache.reconcileSession(
    "session",
    {
      "outputs/image.png": {
        path: "outputs/image.png",
        revision: "v2",
        size: 10,
      },
    },
    false
  );
  expect(cache.has(savedKey)).toBe(false);
  expect(cache.has(otherKey)).toBe(true);
  cache.set(savedKey, savedThumbnail("v2"));
  expect(cache.get(savedKey)?.data?.identity).toBe(
    savedThumbnail("v2").data.identity
  );
  const newKey = "craft-output-thumbnail:session:outputs/new.png";
  cache.reconcileSession(
    "session",
    {
      "outputs/image.png": {
        path: "outputs/image.png",
        revision: "v2",
        size: 10,
      },
      "outputs/new.png": { path: "outputs/new.png", revision: "v1", size: 10 },
    },
    false
  );
  cache.set(newKey, {
    data: {
      ...savedThumbnail().data,
      identity: JSON.stringify([newKey, "v1", 0]),
    },
  });
  expect(cache.has(newKey)).toBe(true);
  expect(cache.has(otherKey)).toBe(true);
});

// React render must not retire the committed owner or write browser storage.
it("keeps committed ownership unchanged when another user is only read during render", () => {
  const current = new OutputThumbnailCache(128, 100000, "committed-owner");
  retainOutputThumbnailCache("committed-owner", current);
  current.set(savedKey, savedThumbnail());
  expect(readOutputThumbnailCache("abandoned-owner")).toBeUndefined();
  expect(readOutputThumbnailCache("committed-owner")).toBe(current);
  expect(current.size).toBe(1);
  const write = jest.spyOn(Storage.prototype, "setItem");
  try {
    const candidate = new OutputThumbnailCache(128, 100000, "committed-owner");
    candidate.get(savedKey);
    expect(write).not.toHaveBeenCalled();
  } finally {
    write.mockRestore();
  }
});
