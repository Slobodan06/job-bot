const SOURCE_COLORS: Record<string, string> = {
  account: "#0b5e75",
  profile: "#0b5e75",
  resume: "#7c3aed",
  ai: "#b45309",
};

export function markField(el: HTMLElement, source: string): void {
  const color = SOURCE_COLORS[source] || "#0b5e75";
  el.style.outline = `2px solid ${color}`;
  el.style.outlineOffset = "1px";
  el.setAttribute("data-jobbot-filled", source);
  const host = el.parentElement;
  if (host) {
    // Idempotent: a field can be (re)filled more than once in a session
    // (Quick fill, then Tailor & fill) — never stack duplicate chips.
    host.querySelectorAll(":scope > .jobbot-chip").forEach((c) => c.remove());
    const chip = document.createElement("span");
    chip.className = "jobbot-chip";
    chip.textContent = source === "ai" ? "JobBot · AI — review" : "JobBot";
    Object.assign(chip.style, {
      position: "absolute",
      transform: "translateY(-100%)",
      marginTop: "-2px",
      background: color,
      color: "#fff",
      font: "600 10px/1.4 system-ui, sans-serif",
      padding: "1px 5px",
      borderRadius: "3px",
      zIndex: "2147483646",
      pointerEvents: "none",
    });
    if (getComputedStyle(host).position === "static") host.style.position = "relative";
    host.appendChild(chip);
  }
}

export function clearMarks(): void {
  document.querySelectorAll<HTMLElement>("[data-jobbot-filled]").forEach((el) => {
    el.style.outline = "";
    el.removeAttribute("data-jobbot-filled");
  });
  document.querySelectorAll(".jobbot-chip").forEach((c) => c.remove());
}
