import { type Packet, PacketType } from "@/app/app/services/streamingModels";
import { type CachedRead, readOnce } from "@/lib/chat/packetReads";

function packet(type: PacketType): Packet {
  // Only the type matters to readOnce
  return {
    placement: { turn_index: 0, tab_index: 0 },
    obj: { type },
  } as unknown as Packet;
}

describe("readOnce", () => {
  test("reads again only when a packet of the watched types arrives", () => {
    const cache = new WeakMap<Packet[], CachedRead<number>>();
    const read = jest.fn((packets: Packet[]) => packets.length);
    const watched = new Set<string>([PacketType.PUBLISH_FILES_END]);
    const packets = [packet(PacketType.MESSAGE_DELTA)];

    expect(readOnce(cache, packets, watched, read)).toBe(1);
    // A packet of another type keeps the read
    packets.push(packet(PacketType.MESSAGE_DELTA));
    expect(readOnce(cache, packets, watched, read)).toBe(1);
    expect(read).toHaveBeenCalledTimes(1);

    packets.push(packet(PacketType.PUBLISH_FILES_END));
    expect(readOnce(cache, packets, watched, read)).toBe(3);
    expect(read).toHaveBeenCalledTimes(2);

    // A replay replaces the array, which reads again
    expect(readOnce(cache, [...packets], watched, read)).toBe(3);
    expect(read).toHaveBeenCalledTimes(3);
  });
});
