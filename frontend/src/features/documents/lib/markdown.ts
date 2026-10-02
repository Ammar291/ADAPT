/**
 * A deliberately tiny markdown parser for drafts ADAPT writes: headings, paragraphs (with
 * line breaks), bold, italic, bulleted and numbered lists, checkboxes and safe links.
 *
 * It produces a plain data tree that the renderer turns into React elements, so text is
 * always escaped by React. Raw HTML in the source stays literal text; it is never injected.
 */

export type Inline =
  | { type: "text"; text: string }
  | { type: "strong"; text: string }
  | { type: "em"; text: string }
  | { type: "code"; text: string }
  | { type: "link"; text: string; href: string };

export interface ListItem {
  /** null for a plain bullet, true/false for a checkbox. */
  checked: boolean | null;
  content: Inline[];
}

export type Block =
  | { type: "heading"; level: 1 | 2 | 3; content: Inline[] }
  | { type: "paragraph"; lines: Inline[][] }
  | { type: "list"; ordered: boolean; items: ListItem[] }
  | { type: "quote"; lines: Inline[][] }
  | { type: "rule" };

const HEADING = /^(#{1,6})\s+(.*?)\s*#*\s*$/;
const BULLET = /^\s{0,3}[-*+]\s+(.*)$/;
const ORDERED = /^\s{0,3}\d{1,3}[.)]\s+(.*)$/;
const CHECKBOX = /^\[( |x|X)\]\s+(.*)$/;
const RULE = /^\s{0,3}([-*_])(\s*\1){2,}\s*$/;
const QUOTE = /^\s{0,3}>\s?(.*)$/;

/** Only web and mail links are ever rendered as links. */
export function safeHref(href: string): string | null {
  const trimmed = href.trim();
  if (/^https?:\/\//i.test(trimmed) || /^mailto:/i.test(trimmed)) {
    try {
      const url = new URL(trimmed);
      return url.protocol === "http:" || url.protocol === "https:" || url.protocol === "mailto:" ? url.href : null;
    } catch {
      return null;
    }
  }
  return null;
}

const INLINE = /\*\*(.+?)\*\*|__(.+?)__|\[([^\]\n]+)\]\(([^)\s]+)\)|`([^`\n]+)`|(?<![\w*])\*(?![\s*])(.+?)(?<![\s*])\*(?![\w*])/g;

export function parseInline(source: string): Inline[] {
  const out: Inline[] = [];
  const push = (node: Inline) => {
    const last = out[out.length - 1];
    if (node.type === "text" && last?.type === "text") last.text += node.text;
    else if (node.type !== "text" || node.text) out.push(node);
  };
  let index = 0;
  for (const match of source.matchAll(INLINE)) {
    const at = match.index ?? 0;
    if (at > index) push({ type: "text", text: source.slice(index, at) });
    const [whole, strongA, strongB, linkText, linkHref, code, em] = match;
    if (strongA !== undefined || strongB !== undefined) push({ type: "strong", text: (strongA ?? strongB)! });
    else if (linkText !== undefined && linkHref !== undefined) {
      const href = safeHref(linkHref);
      push(href ? { type: "link", text: linkText, href } : { type: "text", text: linkText });
    } else if (code !== undefined) push({ type: "code", text: code });
    else if (em !== undefined) push({ type: "em", text: em });
    else push({ type: "text", text: whole });
    index = at + whole.length;
  }
  if (index < source.length) push({ type: "text", text: source.slice(index) });
  return out;
}

function listItem(text: string): ListItem {
  const box = CHECKBOX.exec(text);
  if (box) return { checked: box[1] !== " ", content: parseInline(box[2]!) };
  return { checked: null, content: parseInline(text) };
}

export function parseMarkdown(source: string): Block[] {
  const lines = source.replace(/\r\n?/g, "\n").split("\n");
  const blocks: Block[] = [];
  let paragraph: Inline[][] | null = null;
  let quote: Inline[][] | null = null;
  let list: Extract<Block, { type: "list" }> | null = null;

  const flush = () => {
    if (paragraph) blocks.push({ type: "paragraph", lines: paragraph });
    if (quote) blocks.push({ type: "quote", lines: quote });
    if (list) blocks.push(list);
    paragraph = null;
    quote = null;
    list = null;
  };

  for (const line of lines) {
    if (!line.trim()) {
      flush();
      continue;
    }
    const heading = HEADING.exec(line);
    if (heading) {
      flush();
      const level = Math.min(3, heading[1]!.length) as 1 | 2 | 3;
      blocks.push({ type: "heading", level, content: parseInline(heading[2]!) });
      continue;
    }
    if (RULE.test(line)) {
      flush();
      blocks.push({ type: "rule" });
      continue;
    }
    const bullet = BULLET.exec(line);
    const ordered = bullet ? null : ORDERED.exec(line);
    if (bullet || ordered) {
      const isOrdered = Boolean(ordered);
      const current = list as Extract<Block, { type: "list" }> | null;
      if (!current || current.ordered !== isOrdered) {
        flush();
        list = { type: "list", ordered: isOrdered, items: [] };
      }
      list!.items.push(listItem((bullet ?? ordered)![1]!));
      continue;
    }
    const quoted = QUOTE.exec(line);
    if (quoted) {
      if (!quote) {
        flush();
        quote = [];
      }
      quote.push(parseInline(quoted[1]!));
      continue;
    }
    // A line that follows a list item without a blank line continues that item.
    const openList = list as Extract<Block, { type: "list" }> | null;
    if (openList && /^\s+/.test(line)) {
      const last = openList.items[openList.items.length - 1]!;
      last.content.push({ type: "text", text: " " }, ...parseInline(line.trim()));
      continue;
    }
    if (!paragraph) {
      flush();
      paragraph = [];
    }
    paragraph.push(parseInline(line.trim()));
  }
  flush();
  return blocks;
}

function inlineText(content: Inline[]): string {
  return content.map((node) => (node.type === "link" ? `${node.text} (${node.href.replace(/^mailto:/, "")})` : node.text)).join("");
}

/** Readable plain text for "Copy text": markdown markers removed, lists kept as bullets. */
export function markdownToPlainText(source: string): string {
  return parseMarkdown(source)
    .map((block) => {
      switch (block.type) {
        case "heading":
          return inlineText(block.content);
        case "paragraph":
        case "quote":
          return block.lines.map(inlineText).join("\n");
        case "list":
          return block.items
            .map((item, i) => {
              const marker = block.ordered ? `${i + 1}.` : item.checked === null ? "-" : item.checked ? "[x]" : "[ ]";
              return `${marker} ${inlineText(item.content)}`;
            })
            .join("\n");
        case "rule":
          return "";
      }
    })
    .join("\n\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}
