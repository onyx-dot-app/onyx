import type { Element, ElementContent, Root } from "hast";

import { rehypeDirection } from "@/lib/rehypeDirection";

function el(tagName: string, children: ElementContent[] = []): Element {
  return { type: "element", tagName, properties: {}, children };
}

function txt(value: string): ElementContent {
  return { type: "text", value };
}

function run(...children: ElementContent[]): Root {
  const tree: Root = { type: "root", children };
  rehypeDirection()(tree);
  return tree;
}

function dirOf(node: ElementContent): unknown {
  return node.type === "element" ? node.properties.dir : undefined;
}

describe("rehypeDirection", () => {
  it("stamps rtl on blocks led by RTL text, in any RTL script", () => {
    const arabic = el("p", [txt("مرحبا بالعالم")]);
    const hebrew = el("p", [txt("שלום עולם")]);
    const farsi = el("h2", [txt("سلام دنیا")]);
    run(arabic, hebrew, farsi);
    expect(dirOf(arabic)).toBe("rtl");
    expect(dirOf(hebrew)).toBe("rtl");
    expect(dirOf(farsi)).toBe("rtl");
  });

  it("stamps ltr on blocks led by LTR text", () => {
    const p = el("p", [txt("Hello world")]);
    run(p);
    expect(dirOf(p)).toBe("ltr");
  });

  it("resolves loose-list items through their inline p children", () => {
    // Markdown loose lists render li > p. dir="auto" on the li would skip
    // the dir-carrying p and fall back to LTR. The plugin must not.
    const arabicItem = el("li", [txt("\n"), el("p", [txt("اقرأ الكود")])]);
    const englishItem = el("li", [txt("\n"), el("p", [txt("Read code")])]);
    const list = el("ul", [englishItem, arabicItem]);
    run(list);
    expect(dirOf(list)).toBe("ltr");
    expect(dirOf(englishItem)).toBe("ltr");
    expect(dirOf(arabicItem)).toBe("rtl");
  });

  it("ignores code when resolving direction and pins pre to ltr", () => {
    const item = el("li", [el("code", [txt("foo")]), txt(" تعني كذا")]);
    const pre = el("pre", [el("code", [txt("const x = 1;")])]);
    run(item, pre);
    expect(dirOf(item)).toBe("rtl");
    expect(dirOf(pre)).toBe("ltr");
  });

  it("skips weak characters (digits, punctuation) before the first letter", () => {
    const p = el("p", [txt('42% — "עברית"')]);
    run(p);
    expect(dirOf(p)).toBe("rtl");
  });

  it("treats Arabic-Indic digits as weak, deciding by the first letter", () => {
    const p = el("p", [txt("\u0662\u0660\u0662\u0666 report")]);
    run(p);
    expect(dirOf(p)).toBe("ltr");
  });

  it("detects less common RTL scripts by script property", () => {
    const p = el("p", [txt("\u{10E88}\u{10E8A} note")]);
    run(p);
    expect(dirOf(p)).toBe("rtl");
  });

  it("treats strong RTL punctuation and NKo digits as strong", () => {
    const q = el("p", [txt("\u061F Error")]);
    const afghani = el("p", [txt("\u060B 100 invoice")]);
    run(afghani);
    expect(dirOf(afghani)).toBe("rtl");
    run(q);
    expect(dirOf(q)).toBe("rtl");
    const nko = el("p", [txt("\u07C1 x")]);
    run(nko);
    expect(dirOf(nko)).toBe("rtl");
  });

  it("honors an LRM before any letter", () => {
    const p = el("p", [txt("\u200E\u0645\u0631\u062d\u0628\u0627")]);
    run(p);
    expect(dirOf(p)).toBe("ltr");
  });

  it("leaves blocks without any letters unstamped", () => {
    const p = el("p", [txt("1234 :-)")]);
    run(p);
    expect(dirOf(p)).toBeUndefined();
  });
});
