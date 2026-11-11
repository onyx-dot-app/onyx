import { renderAsync } from "docx-preview";
import { renderDocx } from "@/lib/docx/renderDocx";

jest.mock("docx-preview", () => ({ renderAsync: jest.fn() }));

it("sanitizes document markup before exposing rendered nodes", async () => {
  jest.mocked(renderAsync).mockImplementation(async (_data, body, styles) => {
    expect(body.isConnected).toBe(false);
    body.innerHTML =
      '<p>Document text</p><img src="x" onerror="alert(1)"><a href="javascript:alert(1)">Link</a>';
    if (styles)
      styles.innerHTML = '<style>.docx { color: black; }</style><img src="x">';
  });
  const result = await renderDocx(new ArrayBuffer(0));
  expect(result.body.textContent).toContain("Document text");
  expect(result.body.querySelector("img")).not.toHaveAttribute("onerror");
  expect(result.body.querySelector("a")).not.toHaveAttribute("href");
  expect(result.styles.children).toHaveLength(2);
  expect(result.styles.firstElementChild?.tagName).toBe("STYLE");
});

async function renderHtml(html: string): Promise<string> {
  jest.mocked(renderAsync).mockImplementation(async (_data, body) => {
    body.innerHTML = html;
  });
  return (await renderDocx(new ArrayBuffer(0))).body.innerHTML;
}

describe("document sanitization", () => {
  function parse(html: string): Document {
    return new DOMParser().parseFromString(html, "text/html");
  }

  it("neutralizes the auto-firing <img onerror> that a crafted <w:sym w:char> injects", async () => {
    // Mirrors renderSymbol: span.innerHTML = `&#x${char};` with a malicious char.
    // The (now harmless) <img> may remain, but the onerror handler must be gone
    // so nothing executes.
    const dirty =
      '<span>&amp;#x41;<img src="x" onerror="window.__pwned=1"></span>';
    const clean = await renderHtml(dirty);

    const img = parse(clean).querySelector("img");
    expect(img?.hasAttribute("onerror")).toBe(false);
    expect(clean).not.toContain("onerror");
  });

  it("removes javascript: hrefs that flow from document relationship targets", async () => {
    const clean = await renderHtml(
      '<a href="javascript:window.__pwned=1">click</a>'
    );

    const anchor = parse(clean).querySelector("a");
    // The anchor text survives, but the dangerous href is dropped.
    expect(anchor?.getAttribute("href") ?? "").not.toMatch(/javascript:/i);
    expect(clean.toLowerCase()).not.toContain("javascript:");
  });

  it("strips inline event-handler attributes from otherwise benign elements", async () => {
    const clean = await renderHtml('<p onmouseover="window.__pwned=1">hi</p>');

    const p = parse(clean).querySelector("p");
    expect(p?.hasAttribute("onmouseover")).toBe(false);
    expect(p?.textContent).toBe("hi");
  });

  it("removes <script> elements", async () => {
    const clean = await renderHtml(
      "<div>text<script>window.__pwned=1</script></div>"
    );
    expect(parse(clean).querySelector("script")).toBeNull();
  });

  it("preserves https hyperlinks and basic document formatting", async () => {
    const dirty =
      '<a href="https://onyx.app">Onyx</a>' +
      "<table><tr><td><b>bold</b> <i>italic</i></td></tr></table>" +
      "<h1>Heading</h1>";
    const doc = parse(await renderHtml(dirty));

    expect(doc.querySelector("a")?.getAttribute("href")).toBe(
      "https://onyx.app"
    );
    expect(doc.querySelector("table")).not.toBeNull();
    expect(doc.querySelector("td b")?.textContent).toBe("bold");
    expect(doc.querySelector("td i")?.textContent).toBe("italic");
    expect(doc.querySelector("h1")?.textContent).toBe("Heading");
  });

  it("keeps mailto links and base64 data-URL images (used by useBase64URL)", async () => {
    const dataUrl =
      "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==";
    const doc = parse(
      await renderHtml(
        `<a href="mailto:hi@onyx.app">mail</a><img src="${dataUrl}">`
      )
    );

    expect(doc.querySelector("a")?.getAttribute("href")).toBe(
      "mailto:hi@onyx.app"
    );
    expect(doc.querySelector("img")?.getAttribute("src")).toBe(dataUrl);
  });

  it("blocks data: URLs in anchor hrefs (only permitted in <img src>)", async () => {
    const doc = parse(
      await renderHtml(
        '<a href="data:text/html,<script>alert(1)</script>">x</a>'
      )
    );

    const href = doc.querySelector("a")?.getAttribute("href") ?? "";
    expect(href).not.toMatch(/^data:/i);
  });
});
