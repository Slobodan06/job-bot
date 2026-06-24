import { Box, rem } from "@mantine/core";

type PreviewProps = {
  templateKey: string;
  accentColor: string;
  layoutFamily?: string;
};

function PageShell({ children, scale = 0.42 }: { children: React.ReactNode; scale?: number }) {
  return (
    <Box
      style={{
        width: "100%",
        aspectRatio: "8.5 / 11",
        maxHeight: rem(220),
        overflow: "hidden",
        borderRadius: rem(6),
        background: "#1a1b1e",
        display: "flex",
        alignItems: "flex-start",
        justifyContent: "center",
        padding: rem(4),
      }}
    >
      <Box
        style={{
          width: rem(340),
          height: rem(440),
          background: "#fff",
          borderRadius: rem(2),
          boxShadow: "0 4px 20px rgba(0,0,0,0.35)",
          transform: `scale(${scale})`,
          transformOrigin: "top center",
          overflow: "hidden",
          flexShrink: 0,
          fontFamily: "system-ui, -apple-system, Segoe UI, sans-serif",
        }}
      >
        {children}
      </Box>
    </Box>
  );
}

function Line({ w = "100%", h = 3, c = "#e2e8f0", mb = 4 }: { w?: string | number; h?: number; c?: string; mb?: number }) {
  return <Box style={{ width: w, height: h, background: c, borderRadius: 1, marginBottom: mb }} />;
}

function TextLine({ w = "80%", h = 4, mb = 3 }: { w?: string | number; h?: number; mb?: number }) {
  return <Box style={{ width: w, height: h, background: "#cbd5e1", borderRadius: 1, marginBottom: mb }} />;
}

function SectionTitle({ color = "#0f7669", label }: { color?: string; label: string }) {
  return (
    <Box style={{ fontSize: 6, fontWeight: 700, color, letterSpacing: 1.2, marginBottom: 3, marginTop: 6, textTransform: "uppercase" }}>
      {label}
    </Box>
  );
}

function ClassicPreview() {
  return (
    <PageShell>
      <Box p={10}>
        <Box style={{ fontSize: 10, fontWeight: 700, color: "#0f172a", marginBottom: 2 }}>Alex Morgan</Box>
        <Box style={{ fontSize: 6, color: "#64748b", marginBottom: 6 }}>Senior Software Engineer</Box>
        <Line w="100%" h={2} c="#0d9488" mb={6} />
        <SectionTitle label="Summary" />
        <TextLine w="95%" h={2} /><TextLine w="88%" h={2} /><TextLine w="70%" h={2} mb={4} />
        <SectionTitle label="Experience" />
        <TextLine w="75%" h={3} mb={2} /><TextLine w="100%" h={2} /><TextLine w="92%" h={2} /><TextLine w="85%" h={2} mb={4} />
        <SectionTitle label="Skills" />
        <TextLine w="80%" h={2} /><TextLine w="65%" h={2} />
      </Box>
    </PageShell>
  );
}

function ExecutiveBandPreview({ accent }: { accent: string }) {
  return (
    <PageShell>
      <Box style={{ background: accent, padding: "16px 14px", textAlign: "center" }}>
        <Box style={{ fontSize: 12, fontWeight: 700, color: "#fff" }}>Alex Morgan</Box>
        <Box style={{ fontSize: 7, color: "#c5dae6", marginTop: 4 }}>Senior Software Engineer</Box>
      </Box>
      <Box p={14}>
        <SectionTitle color={accent} label="PROFESSIONAL SUMMARY" />
        <TextLine w="100%" /><TextLine w="90%" mb={4} />
        <SectionTitle color={accent} label="EXPERIENCE" />
        <TextLine w="70%" h={4} /><TextLine w="100%" /><TextLine w="88%" />
      </Box>
    </PageShell>
  );
}

function TwoColumnPreview() {
  return (
    <PageShell>
      <Box style={{ display: "flex", height: "100%" }}>
        <Box style={{ width: "32%", background: "#eef4f8", padding: 10, borderRight: "1px solid #cbd5e1" }}>
          <Box style={{ fontSize: 6, fontWeight: 700, color: "#0f172a", marginBottom: 6 }}>SKILLS</Box>
          <TextLine w="90%" h={3} mb={2} /><TextLine w="80%" h={3} mb={2} /><TextLine w="85%" h={3} mb={8} />
          <Box style={{ fontSize: 6, fontWeight: 700, color: "#0f172a", marginBottom: 4 }}>EDUCATION</Box>
          <TextLine w="95%" h={3} />
        </Box>
        <Box style={{ flex: 1, padding: 10 }}>
          <Box style={{ fontSize: 10, fontWeight: 700, color: "#0f172a" }}>Alex Morgan</Box>
          <SectionTitle label="SUMMARY" />
          <TextLine w="100%" /><TextLine w="85%" mb={4} />
          <SectionTitle label="EXPERIENCE" />
          <TextLine w="75%" h={4} /><TextLine w="100%" /><TextLine w="90%" />
        </Box>
      </Box>
    </PageShell>
  );
}

function NavySidebarPreview({ accent }: { accent: string }) {
  return (
    <PageShell>
      <Box style={{ display: "flex", height: "100%" }}>
        <Box style={{ width: "34%", background: accent, padding: 10 }}>
          <Box style={{ fontSize: 6, fontWeight: 700, color: "#fff", marginBottom: 6 }}>CONTACT</Box>
          <Box style={{ height: 3, background: "rgba(255,255,255,0.4)", marginBottom: 3, width: "90%" }} />
          <Box style={{ height: 3, background: "rgba(255,255,255,0.3)", marginBottom: 8, width: "70%" }} />
          <Box style={{ fontSize: 6, fontWeight: 700, color: "#fff", marginBottom: 4 }}>SKILLS</Box>
          <Box style={{ height: 3, background: "rgba(255,255,255,0.35)", marginBottom: 2, width: "85%" }} />
          <Box style={{ height: 3, background: "rgba(255,255,255,0.35)", marginBottom: 2, width: "75%" }} />
        </Box>
        <Box style={{ flex: 1, padding: 10 }}>
          <Box style={{ fontSize: 10, fontWeight: 700, color: accent }}>Alex Morgan</Box>
          <SectionTitle color={accent} label="PROFILE" />
          <TextLine w="100%" /><TextLine w="88%" mb={4} />
          <SectionTitle color={accent} label="EXPERIENCE" />
          <TextLine w="80%" h={4} /><TextLine w="100%" /><TextLine w="92%" />
        </Box>
      </Box>
    </PageShell>
  );
}

function BorderedCardsPreview() {
  return (
    <PageShell>
      <Box p={10}>
        <Box style={{ border: "1px solid #94a3b8", borderRadius: 3, padding: 8, marginBottom: 8, textAlign: "center" }}>
          <Box style={{ fontSize: 10, fontWeight: 700, color: "#334155" }}>Alex Morgan</Box>
        </Box>
        {["SUMMARY", "EXPERIENCE", "SKILLS"].map((label) => (
          <Box key={label} style={{ border: "1px solid #94a3b8", borderRadius: 3, marginBottom: 6, overflow: "hidden" }}>
            <Box style={{ background: "#f1f5f9", padding: "4px 8px", fontSize: 6, fontWeight: 700, color: "#334155" }}>{label}</Box>
            <Box p={6}><TextLine w="95%" h={3} mb={2} /><TextLine w="80%" h={3} /></Box>
          </Box>
        ))}
      </Box>
    </PageShell>
  );
}

function TimelineAccentPreview({ accent }: { accent: string }) {
  return (
    <PageShell>
      <Box p={12}>
        <Box style={{ fontSize: 11, fontWeight: 700, color: "#0f172a" }}>Alex Morgan</Box>
        <Line w="100%" h={3} c={accent} mb={10} />
        {["SUMMARY", "EXPERIENCE", "SKILLS"].map((label) => (
          <Box key={label} style={{ display: "flex", gap: 6, marginBottom: 8, borderLeft: `3px solid ${accent}`, paddingLeft: 8 }}>
            <Box style={{ flex: 1 }}>
              <Box style={{ fontSize: 6, fontWeight: 700, color: accent, marginBottom: 3 }}>{label}</Box>
              <TextLine w="100%" h={3} mb={2} /><TextLine w="85%" h={3} />
            </Box>
          </Box>
        ))}
      </Box>
    </PageShell>
  );
}

function DenseModernPreview() {
  return (
    <PageShell scale={0.4}>
      <Box p={10}>
        <Box style={{ fontSize: 9, fontWeight: 700, color: "#0f172a", marginBottom: 6 }}>Alex Morgan</Box>
        {["SUMMARY", "EXPERIENCE", "SKILLS", "EDUCATION"].map((label) => (
          <Box key={label} style={{ marginBottom: 5, borderBottom: "1px solid #e2e8f0", paddingBottom: 4 }}>
            <Box style={{ fontSize: 5, fontWeight: 700, color: "#64748b", marginBottom: 2 }}>{label}</Box>
            <TextLine w="98%" h={2} mb={1} /><TextLine w="90%" h={2} mb={1} /><TextLine w="75%" h={2} />
          </Box>
        ))}
      </Box>
    </PageShell>
  );
}

function MinimalCenteredPreview() {
  return (
    <PageShell>
      <Box p={14} style={{ textAlign: "center" }}>
        <Box style={{ fontSize: 12, fontWeight: 700, color: "#0f172a" }}>Alex Morgan</Box>
        <Box style={{ width: "50%", height: 3, background: "#cbd5e1", margin: "4px auto 12px", borderRadius: 1 }} />
        <SectionTitle label="SUMMARY" />
        <TextLine w="90%" /><TextLine w="75%" mb={6} />
        <SectionTitle label="EXPERIENCE" />
        <TextLine w="85%" h={4} /><TextLine w="95%" /><TextLine w="80%" />
      </Box>
    </PageShell>
  );
}

function CorporateBluePreview({ accent }: { accent: string }) {
  return (
    <PageShell>
      <Box p={12}>
        <Box style={{ fontSize: 11, fontWeight: 700, color: "#0f172a" }}>Alex Morgan</Box>
        <TextLine w="55%" h={3} mb={4} />
        <Line w="100%" h={4} c={accent} mb={10} />
        <SectionTitle color={accent} label="PROFESSIONAL SUMMARY" />
        <TextLine w="100%" /><TextLine w="88%" mb={6} />
        <SectionTitle color={accent} label="EXPERIENCE" />
        <TextLine w="72%" h={4} /><TextLine w="100%" /><TextLine w="90%" />
      </Box>
    </PageShell>
  );
}

function WarmAccentPreview({ accent }: { accent: string }) {
  return (
    <PageShell>
      <Box p={10}>
        <Box style={{ fontSize: 10, fontWeight: 700, color: "#0f172a", marginBottom: 8 }}>Alex Morgan</Box>
        {[
          ["Profile", 2],
          ["Experience", 3],
          ["Skills", 2],
        ].map(([label, lines]) => (
          <Box key={label as string} style={{ display: "grid", gridTemplateColumns: "52px 1fr", gap: 6, marginBottom: 6, borderBottom: "1px solid #fed7aa", paddingBottom: 4 }}>
            <Box style={{ fontSize: 5, fontWeight: 700, color: accent }}>{label as string}</Box>
            <Box>
              {Array.from({ length: lines as number }).map((_, i) => (
                <TextLine key={i} w={`${95 - i * 8}%`} h={3} mb={2} />
              ))}
            </Box>
          </Box>
        ))}
      </Box>
    </PageShell>
  );
}

function ModernStackPreview({ accent }: { accent: string }) {
  return (
    <PageShell>
      <Box p={10}>
        <Box style={{ fontSize: 10, fontWeight: 700, color: "#0f172a" }}>Alex Morgan</Box>
        <Box style={{ fontSize: 6, color: "#64748b", marginBottom: 4 }}>alex@email.com</Box>
        <Line w="100%" h={2} c={accent} mb={6} />
        {["Summary", "Experience", "Skills"].map((label) => (
          <Box key={label} style={{ borderLeft: `3px solid ${accent}`, paddingLeft: 6, marginBottom: 6 }}>
            <SectionTitle color={accent} label={label} />
            <TextLine w="100%" h={2} mb={2} /><TextLine w="88%" h={2} />
          </Box>
        ))}
      </Box>
    </PageShell>
  );
}

function ModernSplitPreview({ accent }: { accent: string }) {
  return (
    <PageShell>
      <Box style={{ display: "flex", height: "100%" }}>
        <Box style={{ width: "30%", background: "#f8fafc", padding: 8, borderRight: `2px solid ${accent}` }}>
          <Box style={{ fontSize: 5, fontWeight: 700, color: accent, marginBottom: 4 }}>SKILLS</Box>
          <TextLine w="90%" h={2} mb={2} /><TextLine w="80%" h={2} mb={6} />
          <Box style={{ fontSize: 5, fontWeight: 700, color: accent }}>EDUCATION</Box>
          <TextLine w="85%" h={2} />
        </Box>
        <Box style={{ flex: 1, padding: 8 }}>
          <SectionTitle color={accent} label="Summary" />
          <TextLine w="100%" h={2} mb={4} />
          <SectionTitle color={accent} label="Experience" />
          <TextLine w="95%" h={2} /><TextLine w="88%" h={2} />
        </Box>
      </Box>
    </PageShell>
  );
}

function ModernHeroPreview({ accent }: { accent: string }) {
  return (
    <PageShell>
      <Box style={{ background: accent, padding: "10px 10px 8px" }}>
        <Box style={{ fontSize: 10, fontWeight: 700, color: "#fff" }}>Alex Morgan</Box>
        <Box style={{ fontSize: 6, color: "#e2e8f0" }}>Product Designer</Box>
      </Box>
      <Box p={10}>
        <SectionTitle color={accent} label="Summary" />
        <TextLine w="100%" h={2} mb={4} />
        <SectionTitle color={accent} label="Experience" />
        <TextLine w="92%" h={2} /><TextLine w="100%" h={2} />
      </Box>
    </PageShell>
  );
}

function ModernPillPreview({ accent }: { accent: string }) {
  return (
    <PageShell>
      <Box p={10}>
        <Box style={{ fontSize: 10, fontWeight: 700, color: "#0f172a", marginBottom: 2 }}>Alex Morgan</Box>
        <Line w="100%" h={2} c={accent} mb={6} />
        {["Summary", "Experience"].map((label) => (
          <Box key={label} mb={6}>
            <Box style={{ background: "#f1f5f9", borderLeft: `3px solid ${accent}`, padding: "3px 6px", fontSize: 5, fontWeight: 700, color: accent, marginBottom: 4 }}>
              {label.toUpperCase()}
            </Box>
            <TextLine w="100%" h={2} mb={2} /><TextLine w="90%" h={2} />
          </Box>
        ))}
      </Box>
    </PageShell>
  );
}

function ModernLinePreview({ accent }: { accent: string }) {
  return (
    <PageShell>
      <Box p={10}>
        <Box style={{ fontSize: 10, fontWeight: 700, color: "#0f172a" }}>Alex Morgan</Box>
        <Line w="100%" h={1} c="#e2e8f0" mb={6} />
        {["Summary", "Experience", "Skills"].map((label) => (
          <Box key={label} style={{ marginBottom: 5, borderBottom: "1px solid #e2e8f0", paddingBottom: 4 }}>
            <Box style={{ fontSize: 5, fontWeight: 700, color: accent, letterSpacing: 1, marginBottom: 2 }}>{label.toUpperCase()}</Box>
            <TextLine w="98%" h={2} mb={1} /><TextLine w="85%" h={2} />
          </Box>
        ))}
      </Box>
    </PageShell>
  );
}

export function CvTemplatePreview({ templateKey, accentColor, layoutFamily }: PreviewProps) {
  const layout = layoutFamily || templateKey;
  switch (layout) {
    case "clean-classic":
      return <ClassicPreview />;
    case "executive-band":
      return <ExecutiveBandPreview accent={accentColor} />;
    case "two-column":
      return <TwoColumnPreview />;
    case "navy-sidebar":
      return <NavySidebarPreview accent={accentColor} />;
    case "bordered-cards":
      return <BorderedCardsPreview />;
    case "timeline-accent":
      return <TimelineAccentPreview accent={accentColor} />;
    case "dense-modern":
      return <DenseModernPreview />;
    case "minimal-serif":
      return <MinimalCenteredPreview />;
    case "corporate-blue":
      return <CorporateBluePreview accent={accentColor} />;
    case "warm-accent":
      return <WarmAccentPreview accent={accentColor} />;
    case "modern-stack":
      return <ModernStackPreview accent={accentColor} />;
    case "modern-split":
      return <ModernSplitPreview accent={accentColor} />;
    case "modern-hero":
      return <ModernHeroPreview accent={accentColor} />;
    case "modern-pill":
      return <ModernPillPreview accent={accentColor} />;
    case "modern-line":
      return <ModernLinePreview accent={accentColor} />;
    default:
      return <ClassicPreview />;
  }
}

export function cvTemplatePreviewPdfUrl(key: string): string {
  return `/api/cv-templates/${encodeURIComponent(key)}/preview.pdf`;
}
