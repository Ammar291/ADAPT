import { describe, expect, it } from "vitest";
import { markdownToPlainText, parseInline, parseMarkdown, safeHref } from "./markdown";

describe("parseInline", () => {
  it("splits bold, italic, code and text", () => {
    expect(parseInline("**Subject:** Quote *now* and `x`")).toEqual([
      { type: "strong", text: "Subject:" },
      { type: "text", text: " Quote " },
      { type: "em", text: "now" },
      { type: "text", text: " and " },
      { type: "code", text: "x" },
    ]);
  });

  it("keeps raw HTML as literal text", () => {
    expect(parseInline('<img src=x onerror="alert(1)">')).toEqual([{ type: "text", text: '<img src=x onerror="alert(1)">' }]);
  });

  it("renders only http(s) and mailto links", () => {
    expect(parseInline("[TAMM](https://www.tamm.abudhabi)")).toEqual([{ type: "link", text: "TAMM", href: "https://www.tamm.abudhabi/" }]);
    expect(parseInline("[click](javascript:evil)")).toEqual([{ type: "text", text: "click" }]);
  });

  it("does not treat snake_case or lone asterisks as emphasis", () => {
    expect(parseInline("form_prefill and 5 * 3 * 2")).toEqual([{ type: "text", text: "form_prefill and 5 * 3 * 2" }]);
  });
});

describe("safeHref", () => {
  it("rejects scripts and data URLs", () => {
    expect(safeHref("javascript:alert(1)")).toBeNull();
    expect(safeHref("data:text/html,hi")).toBeNull();
    expect(safeHref("mailto:hello@example.com")).toBe("mailto:hello@example.com");
  });
});

describe("parseMarkdown", () => {
  it("parses headings, paragraphs with line breaks and lists", () => {
    const blocks = parseMarkdown("## Company\n\n**Activity:** Software\n\nKind regards,\nSam\n\n- one\n- two\n\n1. first\n2. second");
    expect(blocks.map((b) => b.type)).toEqual(["heading", "paragraph", "paragraph", "list", "list"]);
    expect(blocks[0]).toMatchObject({ type: "heading", level: 2 });
    expect(blocks[2]).toMatchObject({ type: "paragraph", lines: [[{ type: "text", text: "Kind regards," }], [{ type: "text", text: "Sam" }]] });
    expect(blocks[3]).toMatchObject({ type: "list", ordered: false });
    expect(blocks[4]).toMatchObject({ type: "list", ordered: true });
  });

  it("parses checkboxes", () => {
    const [list] = parseMarkdown("- [ ] Get a SIM\n- [x] Book biometrics");
    expect(list).toEqual({
      type: "list",
      ordered: false,
      items: [
        { checked: false, content: [{ type: "text", text: "Get a SIM" }] },
        { checked: true, content: [{ type: "text", text: "Book biometrics" }] },
      ],
    });
  });

  it("clamps deep headings and handles rules and quotes", () => {
    const blocks = parseMarkdown("#### Deep\n\n---\n\n> Note\n> more");
    expect(blocks[0]).toMatchObject({ type: "heading", level: 3 });
    expect(blocks[1]).toEqual({ type: "rule" });
    expect(blocks[2]).toMatchObject({ type: "quote" });
  });

  it("returns nothing for empty input", () => {
    expect(parseMarkdown("  \n\n")).toEqual([]);
  });
});

describe("markdownToPlainText", () => {
  it("removes markers but keeps structure", () => {
    const text = markdownToPlainText("**Subject:** Hello\n\nDear team,\nThanks\n\n- [ ] SIM\n- [x] Visa\n\n## Next");
    expect(text).toBe("Subject: Hello\n\nDear team,\nThanks\n\n[ ] SIM\n[x] Visa\n\nNext");
  });
});
