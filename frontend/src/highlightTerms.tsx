import { Fragment, type ReactNode } from "react";
import { Text } from "@mantine/core";

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function termPattern(term: string): RegExp | null {
  const cleaned = term.trim();
  if (cleaned.length < 2) return null;
  if (/^[\w\-./+#]+$/.test(cleaned)) {
    return new RegExp(`(?<![\\w\\-./+#])${escapeRegExp(cleaned)}(?![\\w\\-./+#])`, "gi");
  }
  return new RegExp(escapeRegExp(cleaned), "gi");
}

/** Bold JD-critical spans inside plain text (mirrors Word export highlighting). */
export function highlightTermsInText(
  text: string,
  terms: string[],
  options?: { boldColor?: string },
): ReactNode {
  if (!text || !terms.length) return text;

  const unique = [...new Set(terms.map((t) => t.trim()).filter((t) => t.length >= 2))].sort(
    (a, b) => b.length - a.length,
  );
  if (!unique.length) return text;

  type Span = { start: number; end: number };
  const spans: Span[] = [];

  for (const term of unique) {
    const pattern = termPattern(term);
    if (!pattern) continue;
    for (const match of text.matchAll(pattern)) {
      if (match.index === undefined) continue;
      const start = match.index;
      const end = start + match[0].length;
      if (spans.some((s) => start < s.end && end > s.start)) continue;
      spans.push({ start, end });
    }
  }

  if (!spans.length) return text;

  spans.sort((a, b) => a.start - b.start);
  const merged: Span[] = [];
  for (const span of spans) {
    const last = merged[merged.length - 1];
    if (last && span.start <= last.end) {
      last.end = Math.max(last.end, span.end);
    } else {
      merged.push({ ...span });
    }
  }

  const nodes: ReactNode[] = [];
  let pos = 0;
  merged.forEach((span, i) => {
    if (span.start > pos) {
      nodes.push(<Fragment key={`t-${i}-pre`}>{text.slice(pos, span.start)}</Fragment>);
    }
    nodes.push(
      <Text
        key={`b-${i}`}
        component="span"
        fw={700}
        c={options?.boldColor ?? "gray.0"}
        inherit
      >
        {text.slice(span.start, span.end)}
      </Text>,
    );
    pos = span.end;
  });
  if (pos < text.length) {
    nodes.push(<Fragment key="tail">{text.slice(pos)}</Fragment>);
  }
  return <>{nodes}</>;
}
