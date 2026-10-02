import { describe, expect, it } from "vitest";
import type { ExtractedField, GeneratedDocument } from "@/domain/documents";
import {
  confidenceLevel,
  diffCorrections,
  humanizeNodeKey,
  isAcceptedType,
  isSensitiveField,
  maskValue,
  parseDocumentKind,
  pipelineOf,
  reviewCount,
  sortDrafts,
  validateUpload,
} from "./documents";

const field = (name: string, value: string | null, needsReview = false, label = name): ExtractedField => ({
  name,
  label,
  value,
  confidence: needsReview ? 0.6 : 0.95,
  needsReview,
});

describe("validateUpload", () => {
  it("accepts images and PDFs under 20 MB", () => {
    expect(validateUpload({ name: "p.jpg", type: "image/jpeg", size: 1000 })).toEqual({ ok: true });
    expect(validateUpload({ name: "c.pdf", type: "application/pdf", size: 20 * 1024 * 1024 })).toEqual({ ok: true });
  });

  it("accepts HEIC photos sent without a MIME type", () => {
    expect(isAcceptedType({ name: "IMG_0001.HEIC", type: "" })).toBe(true);
  });

  it("rejects other types, empty and oversized files with a fix", () => {
    const docx = validateUpload({ name: "a.docx", type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document", size: 10 });
    expect(docx.ok).toBe(false);
    expect(!docx.ok && docx.message).toMatch(/photo .* or a PDF/);
    expect(validateUpload({ name: "a.jpg", type: "image/jpeg", size: 0 }).ok).toBe(false);
    const big = validateUpload({ name: "a.pdf", type: "application/pdf", size: 20 * 1024 * 1024 + 1 });
    expect(!big.ok && big.message).toMatch(/20 MB/);
  });
});

describe("parseDocumentKind", () => {
  it("only accepts known kinds", () => {
    expect(parseDocumentKind("passport", ["passport", "miscellaneous"])).toBe("passport");
    expect(parseDocumentKind("<script>", ["passport"])).toBeNull();
    expect(parseDocumentKind(null, ["passport"])).toBeNull();
  });
});

describe("pipelineOf", () => {
  it("maps each status onto the four steps", () => {
    expect(pipelineOf("uploaded").steps.map((s) => s.state)).toEqual(["done", "current", "todo", "todo"]);
    expect(pipelineOf("processing").busy).toBe(true);
    expect(pipelineOf("needs_review", 2).label).toBe("Check 2 details");
    expect(pipelineOf("needs_review", 1).label).toBe("Check 1 detail");
    expect(pipelineOf("extracted").tone).toBe("ready");
    expect(pipelineOf("confirmed").steps.every((s) => s.state === "done")).toBe(true);
    expect(pipelineOf("failed").steps[1]!.state).toBe("failed");
  });
});

describe("confidenceLevel", () => {
  it("uses words, not numbers", () => {
    expect(confidenceLevel(0.97)).toBe("high");
    expect(confidenceLevel(0.76)).toBe("medium");
    expect(confidenceLevel(0.4)).toBe("low");
  });
});

describe("sensitive values", () => {
  it("recognises document numbers", () => {
    expect(isSensitiveField(field("passport_number", "X", false, "Passport number"))).toBe(true);
    expect(isSensitiveField(field("certificate_number", "X", false, "Certificate number"))).toBe(true);
    expect(isSensitiveField(field("x", "X", false, "Emirates ID card number"))).toBe(true);
    expect(isSensitiveField(field("surname", "X", false, "Surname"))).toBe(false);
    expect(isSensitiveField(field("date_of_birth", "X", false, "Date of birth"))).toBe(false);
  });

  it("masks all but the last four characters", () => {
    expect(maskValue("UT4821937")).toBe("•••••1937");
    expect(maskValue("MC-2019-0847")).toBe("••••••0847");
    expect(maskValue("123")).toBe("••••");
    expect(maskValue(null)).toBe("");
  });
});

describe("diffCorrections", () => {
  const fields = [field("surname", "CARTER"), field("place", "Utopia City", true), field("attestation", null, true)];

  it("returns only changed fields", () => {
    expect(diffCorrections(fields, { surname: "CARTER", place: "Utopia", attestation: "" })).toEqual([{ name: "place", value: "Utopia" }]);
  });

  it("sends cleared values as null and trims", () => {
    expect(diffCorrections(fields, { surname: "  ", attestation: " Stamped 2020 " })).toEqual([
      { name: "surname", value: null },
      { name: "attestation", value: "Stamped 2020" },
    ]);
  });

  it("counts fields to review", () => {
    expect(reviewCount(fields)).toBe(2);
    expect(reviewCount(null)).toBe(0);
  });
});

describe("humanizeNodeKey", () => {
  it("turns a node key into words", () => {
    expect(humanizeNodeKey("residency.entry_permit")).toBe("Entry permit");
    expect(humanizeNodeKey("community.d.hub71")).toBe("Hub71");
  });
});

describe("sortDrafts", () => {
  const d = (id: string, status: GeneratedDocument["status"], updatedAt: string) => ({ id, status, updatedAt }) as GeneratedDocument;
  it("puts drafts waiting for review first", () => {
    const sorted = sortDrafts([
      d("a", "approved", "2026-01-03"),
      d("b", "draft", "2026-01-01"),
      d("c", "discarded", "2026-01-05"),
      d("e", "draft", "2026-01-02"),
    ]);
    expect(sorted.map((x) => x.id)).toEqual(["e", "b", "a", "c"]);
  });
});
