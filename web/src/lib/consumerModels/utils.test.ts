import {
  findConsumerProfile,
  getConsumerProfileLabel,
} from "@/lib/consumerModels/utils";
import { ConsumerModelCatalog } from "@/lib/consumerModels/types";

const catalog: ConsumerModelCatalog = {
  default_profile_id: "balanced",
  profiles: [
    {
      id: "fast",
      label: "快速",
      description: "更快响应",
      supports_image: false,
    },
    {
      id: "balanced",
      label: "均衡",
      description: "默认推荐",
      supports_image: false,
    },
  ],
};

describe("consumer model catalog utils", () => {
  test("finds the requested consumer profile", () => {
    expect(findConsumerProfile(catalog, "fast")?.label).toBe("快速");
  });

  test("falls back to the catalog default profile", () => {
    expect(findConsumerProfile(catalog, "missing")?.id).toBe("balanced");
    expect(findConsumerProfile(catalog, null)?.id).toBe("balanced");
  });

  test("returns a stable label for missing catalog data", () => {
    expect(getConsumerProfileLabel(undefined, "fast")).toBe("模型");
    expect(getConsumerProfileLabel(catalog, "missing")).toBe("均衡");
  });
});
