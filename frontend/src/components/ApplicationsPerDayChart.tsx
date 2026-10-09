import { Box, Button, Group, Paper, SegmentedControl, Skeleton, Stack, Table, Text, Title } from "@mantine/core";
import { IconChartBar, IconTable } from "@tabler/icons-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { adminTrackingApi, type DailyApplications } from "../auth/api";

// Validated (dataviz validate_palette.js, dark mode on #242424): L inside 0.48–0.67, contrast ≥ 3:1.
const BAR = "#0ca678"; // Mantine teal.7
const BAR_HOVER = "#20c997"; // teal.5 — the hovered bar lifts lighter
const GRID = "var(--mantine-color-dark-4)";
const TEXT_MUTED = "var(--mantine-color-dimmed)";

const HEIGHT = 220;
const PAD = { top: 12, right: 8, bottom: 28, left: 34 };
const RANGES = [7, 14, 30, 90];

type Props = {
  memberId: string | null;
  selectedDay: string | null;
  onSelectDay: (day: string | null) => void;
  /** Bump to refetch (e.g. after an edit below). */
  refreshKey?: number;
};

/** "2026-10-08" → local Date (no UTC shift). */
function toDate(iso: string): Date {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d);
}
const fmtShort = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" });
const fmtLong = new Intl.DateTimeFormat(undefined, { weekday: "short", month: "short", day: "numeric" });
export const formatDay = (iso: string) => fmtLong.format(toDate(iso));

/** Clean integer ticks: max rounded up to 1/2/5×10ⁿ, at most ~4 steps. */
function niceTicks(max: number): number[] {
  if (max <= 0) return [0, 1];
  const rough = max / 4;
  const pow = 10 ** Math.floor(Math.log10(rough));
  const step = Math.max(1, [1, 2, 5, 10].map((m) => m * pow).find((s) => s >= rough) ?? pow * 10);
  const top = Math.ceil(max / step) * step;
  return Array.from({ length: top / step + 1 }, (_, i) => i * step);
}

/** Column with a 4px rounded data-end and a square foot on the baseline. */
function columnPath(x: number, y: number, w: number, h: number): string {
  const r = Math.min(4, w / 2, h);
  return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
}

export function ApplicationsPerDayChart({ memberId, selectedDay, onSelectDay, refreshKey = 0 }: Props) {
  const [range, setRange] = useState(30);
  const [data, setData] = useState<DailyApplications | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [hover, setHover] = useState<number | null>(null);
  const [showTable, setShowTable] = useState(false);
  const [width, setWidth] = useState(0);
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    adminTrackingApi
      .daily(memberId, range)
      .then((d) => !cancelled && setData(d))
      .catch((e) => !cancelled && setError(e instanceof Error ? e.message : "Could not load"));
    return () => {
      cancelled = true;
    };
  }, [memberId, range, refreshKey]);

  useEffect(() => {
    const el = boxRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const days = data?.days ?? [];
  const max = Math.max(0, ...days.map((d) => d.count));
  const ticks = useMemo(() => niceTicks(max), [max]);
  const yMax = ticks[ticks.length - 1];
  const innerW = Math.max(0, width - PAD.left - PAD.right);
  const innerH = HEIGHT - PAD.top - PAD.bottom;
  const band = days.length ? innerW / days.length : 0;
  const barW = Math.max(2, Math.min(24, band - 2)); // ≤24px, and always a 2px gap between neighbours
  const y = (v: number) => PAD.top + innerH - (v / yMax) * innerH;
  // Date labels at least ~56px apart.
  const labelEvery = Math.max(1, Math.ceil(56 / Math.max(band, 1)));

  const busiest = days.reduce<(typeof days)[number] | null>((b, d) => (d.count > (b?.count ?? 0) ? d : b), null);
  const avg = days.length ? (data?.total ?? 0) / days.length : 0;
  const hovered = hover != null ? days[hover] : null;

  return (
    <Paper withBorder radius="lg" p={{ base: "md", sm: "lg" }} bg="dark.7">
      <Stack gap="sm">
        <Group justify="space-between" wrap="wrap" gap="xs">
          <Title order={3} size="h5">
            Applications per day
          </Title>
          <Group gap="xs">
            <SegmentedControl
              size="xs"
              value={String(range)}
              onChange={(v) => setRange(Number(v))}
              data={RANGES.map((r) => ({ value: String(r), label: `${r}d` }))}
            />
            <Button
              size="compact-sm"
              variant="subtle"
              color="gray"
              leftSection={showTable ? <IconChartBar size={14} /> : <IconTable size={14} />}
              onClick={() => setShowTable((v) => !v)}
            >
              {showTable ? "Chart" : "Table"}
            </Button>
          </Group>
        </Group>

        {data ? (
          <Group gap="lg" wrap="wrap">
            <Text size="sm">
              <Text span fw={700} size="lg">
                {data.total}
              </Text>{" "}
              <Text span c="dimmed" size="sm">
                in the last {range} days
              </Text>
            </Text>
            <Text size="sm" c="dimmed">
              avg {avg < 10 ? avg.toFixed(1) : Math.round(avg)} / day
            </Text>
            {busiest ? (
              <Text size="sm" c="dimmed">
                busiest {formatDay(busiest.date)} ({busiest.count})
              </Text>
            ) : null}
          </Group>
        ) : null}

        <Box ref={boxRef} pos="relative" style={{ display: showTable ? "none" : undefined }}>
          {error ? (
            <Text c="red" size="sm" py="xl" ta="center">
              {error}
            </Text>
          ) : !data || !width ? (
            <Skeleton h={HEIGHT} radius="md" />
          ) : (
            <svg
              width={width}
              height={HEIGHT}
              role="img"
              aria-label={`Applications per day over the last ${range} days, ${data.total} in total`}
              style={{ display: "block", overflow: "visible" }}
              onPointerLeave={() => setHover(null)}
            >
              {ticks.map((t) => (
                <g key={t}>
                  <line x1={PAD.left} x2={width - PAD.right} y1={y(t)} y2={y(t)} stroke={GRID} strokeWidth={1} />
                  <text x={PAD.left - 8} y={y(t)} dy="0.32em" textAnchor="end" fontSize={11} fill={TEXT_MUTED}>
                    {t.toLocaleString()}
                  </text>
                </g>
              ))}
              {days.map((d, i) => {
                const cx = PAD.left + band * i + band / 2;
                const h = (d.count / yMax) * innerH;
                const dimmed = selectedDay != null && selectedDay !== d.date;
                const showLabel = (days.length - 1 - i) % labelEvery === 0; // anchor labels on today
                return (
                  <g key={d.date}>
                    {d.count > 0 ? (
                      <path
                        d={columnPath(cx - barW / 2, y(d.count), barW, h)}
                        fill={hover === i ? BAR_HOVER : BAR}
                        opacity={dimmed ? 0.35 : 1}
                      />
                    ) : null}
                    {showLabel ? (
                      <text x={cx} y={HEIGHT - 8} textAnchor="middle" fontSize={11} fill={TEXT_MUTED}>
                        {fmtShort.format(toDate(d.date))}
                      </text>
                    ) : null}
                    {/* Hit target: the whole column band, bigger than the bar itself. */}
                    <rect
                      x={PAD.left + band * i}
                      y={PAD.top}
                      width={band}
                      height={innerH}
                      fill="transparent"
                      style={{ cursor: "pointer", outline: "none" }}
                      tabIndex={0}
                      role="button"
                      aria-pressed={selectedDay === d.date}
                      aria-label={`${formatDay(d.date)}: ${d.count} application${d.count === 1 ? "" : "s"}`}
                      onPointerEnter={() => setHover(i)}
                      onFocus={() => setHover(i)}
                      onBlur={() => setHover(null)}
                      onClick={() => onSelectDay(selectedDay === d.date ? null : d.date)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          onSelectDay(selectedDay === d.date ? null : d.date);
                        }
                      }}
                    />
                  </g>
                );
              })}
              <line
                x1={PAD.left}
                x2={width - PAD.right}
                y1={PAD.top + innerH}
                y2={PAD.top + innerH}
                stroke={GRID}
                strokeWidth={1}
              />
            </svg>
          )}

          {hovered && hover != null ? (
            <Paper
              shadow="md"
              radius="md"
              p="xs"
              withBorder
              style={{
                position: "absolute",
                top: 0,
                left: Math.min(Math.max(PAD.left + band * hover + band / 2 - 90, 0), Math.max(width - 180, 0)),
                width: 180,
                pointerEvents: "none",
                zIndex: 2,
              }}
            >
              <Text fw={700} size="sm">
                {hovered.count} application{hovered.count === 1 ? "" : "s"}
              </Text>
              <Text size="xs" c="dimmed" mb={hovered.members.length ? 4 : 0}>
                {formatDay(hovered.date)}
              </Text>
              {hovered.members.map((m) => (
                <Group key={m.id} justify="space-between" gap={6} wrap="nowrap">
                  <Text size="xs" truncate>
                    {m.name}
                  </Text>
                  <Text size="xs" fw={600}>
                    {m.count}
                  </Text>
                </Group>
              ))}
              {hovered.count > 0 ? (
                <Text size="xs" c="dimmed" mt={4}>
                  {selectedDay === hovered.date ? "Click to show all days" : "Click to list this day"}
                </Text>
              ) : null}
            </Paper>
          ) : null}
        </Box>

        {showTable && data ? (
          <Table.ScrollContainer minWidth={320} mah={320}>
            <Table striped highlightOnHover verticalSpacing={4}>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Day</Table.Th>
                  <Table.Th ta="right">Applications</Table.Th>
                  <Table.Th>Top members</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {[...days].reverse().map((d) => (
                  <Table.Tr
                    key={d.date}
                    onClick={() => onSelectDay(selectedDay === d.date ? null : d.date)}
                    style={{ cursor: "pointer" }}
                    bg={selectedDay === d.date ? "var(--mantine-color-teal-light)" : undefined}
                  >
                    <Table.Td>{formatDay(d.date)}</Table.Td>
                    <Table.Td ta="right" fw={d.count ? 600 : undefined} c={d.count ? undefined : "dimmed"}>
                      {d.count}
                    </Table.Td>
                    <Table.Td>
                      <Text size="xs" c="dimmed" lineClamp={1}>
                        {d.members.map((m) => `${m.name} (${m.count})`).join(", ") || "—"}
                      </Text>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        ) : null}
      </Stack>
    </Paper>
  );
}
