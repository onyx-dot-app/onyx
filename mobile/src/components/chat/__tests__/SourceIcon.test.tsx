import { describe, expect, it } from "@jest/globals";
import { render } from "@testing-library/react-native";
import { Image } from "expo-image";
import { makeSearchDoc } from "@/chat/__tests__/fixtures";
import { SourceIcon } from "@/components/chat/SourceIcon";

describe("SourceIcon privacy", () => {
  it.each(["web", "confluence", "google_drive"])(
    "keeps %s connector icons local",
    (source) => {
      const { UNSAFE_queryAllByType, rerender } = render(
        <SourceIcon
          doc={makeSearchDoc({ source_type: source, is_internet: false })}
        />,
      );
      expect(UNSAFE_queryAllByType(Image)).toHaveLength(0);
      rerender(<SourceIcon doc={makeSearchDoc({ is_internet: true })} />);
      expect(UNSAFE_queryAllByType(Image)).toHaveLength(1);
    },
  );
});
