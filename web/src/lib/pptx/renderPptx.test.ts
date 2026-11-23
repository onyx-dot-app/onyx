/**
 * @jest-environment jsdom
 */
import { pptxToHtml } from "@jvmr/pptx-to-html";
import { renderPptx } from "@/lib/pptx/renderPptx";

jest.mock("@jvmr/pptx-to-html", () => ({
  pptxToHtml: jest.fn(),
}));

const IMAGE = "data:image/png;base64,AAAA";

/** The background image that a slide box with `style` keeps. */
async function keptBackground(style: string): Promise<string> {
  jest
    .mocked(pptxToHtml)
    .mockResolvedValue([`<div style='${style}; color: red'>Text</div>`]);
  const [slide] = await renderPptx(new ArrayBuffer(0));
  const template = document.createElement("template");
  template.innerHTML = slide ?? "";
  const box = template.content.querySelector<HTMLElement>("div");
  expect(box?.style.color).toBe("red");
  return box?.style.backgroundImage ?? "";
}

/** A slide's sanitized markup, parsed. */
async function renderedSlide(html: string): Promise<DocumentFragment> {
  jest.mocked(pptxToHtml).mockResolvedValue([html]);
  const [slide] = await renderPptx(new ArrayBuffer(0));
  const template = document.createElement("template");
  template.innerHTML = slide ?? "";
  return template.content;
}

const OUTSIDE = "https://tracker.example/pixel.png";
const XLINK = "http://www.w3.org/1999/xlink";

describe("renderPptx", () => {
  test("keeps an embedded image in a quoted url()", async () => {
    expect(await keptBackground(`background-image: url("${IMAGE}")`)).toBe(
      `url("${IMAGE}")`
    );
  });

  test("removes a url() that loads from outside the deck", async () => {
    expect(
      await keptBackground(
        `background-image: url("https://tracker.example/bg.png")`
      )
    ).toBe("");
    expect(
      await keptBackground(
        "background-image: url(https://tracker.example/bg.png)"
      )
    ).toBe("");
  });

  test("removes a value with an embedded image and an outside url()", async () => {
    expect(
      await keptBackground(
        `background-image: url("${IMAGE}"), url("https://tracker.example/bg.png")`
      )
    ).toBe("");
  });

  test("removes an SVG image href that loads from outside the deck", async () => {
    const slide = await renderedSlide(
      `<svg><image href="${OUTSIDE}"></image><image href="${IMAGE}"></image></svg>`
    );
    const [outside, embedded] = Array.from(slide.querySelectorAll("image"));
    expect(outside?.hasAttribute("href")).toBe(false);
    expect(embedded?.getAttribute("href")).toBe(IMAGE);
  });

  test("removes an xlink:href that loads from outside the deck", async () => {
    const slide = await renderedSlide(
      `<svg xmlns:xlink="${XLINK}"><image xlink:href="${OUTSIDE}"></image><image xlink:href="${IMAGE}"></image></svg>`
    );
    const [outside, embedded] = Array.from(slide.querySelectorAll("image"));
    expect(outside?.hasAttributeNS(XLINK, "href")).toBe(false);
    expect(embedded?.getAttributeNS(XLINK, "href")).toBe(IMAGE);
  });

  test("removes a srcset that loads from outside the deck", async () => {
    const slide = await renderedSlide(
      `<img src="${IMAGE}" srcset="${OUTSIDE} 2x">`
    );
    const image = slide.querySelector("img");
    expect(image?.hasAttribute("srcset")).toBe(false);
    expect(image?.getAttribute("src")).toBe(IMAGE);
  });

  test("keeps a link's href", async () => {
    const slide = await renderedSlide(
      `<a href="https://example.com/docs">Docs</a>`
    );
    expect(slide.querySelector("a")?.getAttribute("href")).toBe(
      "https://example.com/docs"
    );
  });
});
