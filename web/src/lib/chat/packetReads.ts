import type { Packet } from "@/app/app/services/streamingModels";

export interface CachedRead<T> {
  count: number;
  read: T;
}

/**
 * Streams append to a response's packet array and a replay replaces it, so a
 * read stays valid for the same array until a packet of `types` arrives.
 * Packets that cannot change the result keep the same read object.
 */
export function readOnce<T>(
  cache: WeakMap<Packet[], CachedRead<T>>,
  packets: Packet[],
  types: ReadonlySet<string>,
  read: (packets: Packet[]) => T
): T {
  const cached = cache.get(packets);
  if (cached && cached.count <= packets.length) {
    let changed = false;
    for (
      let index = cached.count;
      index < packets.length && !changed;
      index++
    ) {
      const type = packets[index]?.obj.type;
      changed = type !== undefined && types.has(type);
    }
    if (!changed) {
      cached.count = packets.length;
      return cached.read;
    }
  }
  const result = read(packets);
  cache.set(packets, { count: packets.length, read: result });
  return result;
}
