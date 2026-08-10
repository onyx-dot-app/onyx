import { describe, expect, it } from "@jest/globals";
import { render } from "@testing-library/react-native";

import { KNOWN_SOURCES } from "@/chat/sources";
import { ConnectorSourceIcon } from "@/components/chat/ConnectorSourceIcon";

describe("ConnectorSourceIcon", () => {
  // The logos are machine-translated web SVGs; an element react-native-svg lacks only fails here.
  it.each(KNOWN_SOURCES)("renders the %s mark", (source) => {
    expect(
      render(<ConnectorSourceIcon source={source} />).toJSON(),
    ).toBeTruthy();
  });

  it("falls back to a glyph for a source it can't name", () => {
    expect(
      render(<ConnectorSourceIcon source="some_future_connector" />).toJSON(),
    ).toBeTruthy();
  });
});
