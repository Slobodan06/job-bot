import {
  Alert,
  Badge,
  Box,
  Button,
  Container,
  Group,
  Paper,
  SegmentedControl,
  SimpleGrid,
  Skeleton,
  Stack,
  Table,
  Text,
  Title,
  Tooltip,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconAlertTriangle, IconCoin, IconRefresh } from "@tabler/icons-react";
import { useCallback, useEffect, useState } from "react";

import { aiUsageApi, type AiUsageReport } from "../auth/api";

const RANGES = [7, 30, 90];
const BAR = "#0ca678"; // same validated teal as the applications chart

const usd = (v: number) =>
  v >= 1 ? `$${v.toFixed(2)}` : v > 0 ? `$${v.toFixed(v < 0.01 ? 4 : 3)}` : "$0";
const compact = new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 });

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(iso));
}

function StatTile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <Paper withBorder radius="md" p="md" bg="dark.7">
      <Text size="xs" c="dimmed" tt="uppercase" fw={600}>
        {label}
      </Text>
      <Text fw={700} fz={28} lh={1.2}>
        {value}
      </Text>
      {hint ? (
        <Text size="xs" c="dimmed">
          {hint}
        </Text>
      ) : null}
    </Paper>
  );
}

/** Owner view: who uses the OpenAI credits (estimated from token counts × model prices). */
export default function AiUsagePage() {
  const [days, setDays] = useState(30);
  const [report, setReport] = useState<AiUsageReport | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setReport(await aiUsageApi.report(days));
    } catch (e) {
      notifications.show({ title: "Could not load AI usage", message: (e as Error).message, color: "red" });
    } finally {
      setLoading(false);
    }
  }, [days]);

  useEffect(() => {
    void load();
  }, [load]);

  const maxCost = Math.max(0, ...(report?.members.map((m) => m.cost_usd) ?? []));

  return (
    <Container size="xl" py={{ base: "md", sm: "xl" }} px={{ base: "sm", md: "md" }}>
      <Stack gap="lg">
        <Group justify="space-between" align="flex-end" wrap="wrap">
          <Stack gap={4}>
            <Group gap="xs">
              <IconCoin size={24} stroke={1.5} />
              <Title order={2}>AI usage</Title>
            </Group>
            <Text c="dimmed" size="sm" maw={680}>
              OpenAI usage per member — every tailored resume, cover letter, answer and resume parse is counted.
              Costs are estimates from token counts and model prices; check exact billing in your OpenAI dashboard.
            </Text>
          </Stack>
          <Group gap="xs">
            <SegmentedControl
              value={String(days)}
              onChange={(v) => setDays(Number(v))}
              data={RANGES.map((r) => ({ value: String(r), label: `${r} days` }))}
            />
            <Button variant="light" color="teal" leftSection={<IconRefresh size={16} />} onClick={load} loading={loading}>
              Refresh
            </Button>
          </Group>
        </Group>

        {report ? (
          <SimpleGrid cols={{ base: 1, sm: 3 }} spacing="sm">
            <StatTile label="Estimated spend" value={usd(report.total_cost_usd)} hint={`last ${report.days} days`} />
            <StatTile label="AI requests" value={report.total_requests.toLocaleString()} />
            <StatTile label="Tokens" value={compact.format(report.total_tokens)} />
          </SimpleGrid>
        ) : (
          <Skeleton h={96} radius="md" />
        )}

        {report?.unpriced_models.length ? (
          <Alert color="yellow" variant="light" icon={<IconAlertTriangle size={18} />}>
            No price is known for: <b>{report.unpriced_models.join(", ")}</b> — their tokens are counted but their cost
            shows as $0. Set <code>OPENAI_PRICING_JSON</code> on the server to price them.
          </Alert>
        ) : null}

        <Paper withBorder radius="lg" bg="dark.7" style={{ overflow: "hidden" }}>
          <Box style={{ overflowX: "auto" }}>
            <Table highlightOnHover verticalSpacing="sm" miw={860}>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th w={40}>#</Table.Th>
                  <Table.Th>Member</Table.Th>
                  <Table.Th>Estimated spend</Table.Th>
                  <Table.Th ta="right">Requests</Table.Th>
                  <Table.Th ta="right">Tokens (in / out)</Table.Th>
                  <Table.Th>Top features</Table.Th>
                  <Table.Th>Last used</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {report?.members.map((m, i) => {
                  const share = report.total_cost_usd ? (m.cost_usd / report.total_cost_usd) * 100 : 0;
                  return (
                    <Table.Tr key={m.member_id ?? "system"}>
                      <Table.Td>
                        <Text fw={700} c={i === 0 && m.cost_usd > 0 ? "red.4" : undefined}>
                          {i + 1}
                        </Text>
                      </Table.Td>
                      <Table.Td>
                        <Text fw={600} size="sm">
                          {m.name || "—"}
                        </Text>
                        <Text size="xs" c="dimmed">
                          {m.email}
                        </Text>
                      </Table.Td>
                      <Table.Td miw={200}>
                        <Group gap="xs" wrap="nowrap">
                          <Text fw={700} size="sm" w={70}>
                            {usd(m.cost_usd)}
                          </Text>
                          <Tooltip label={`${share.toFixed(1)}% of all estimated spend`} withArrow>
                            <Box w={110} h={8} bg="dark.5" style={{ borderRadius: 4, overflow: "hidden" }}>
                              <Box
                                h={8}
                                w={`${maxCost ? Math.max((m.cost_usd / maxCost) * 100, m.cost_usd > 0 ? 3 : 0) : 0}%`}
                                bg={BAR}
                                style={{ borderRadius: 4 }}
                              />
                            </Box>
                          </Tooltip>
                        </Group>
                      </Table.Td>
                      <Table.Td ta="right">{m.requests.toLocaleString()}</Table.Td>
                      <Table.Td ta="right">
                        <Text size="sm">{compact.format(m.total_tokens)}</Text>
                        <Text size="xs" c="dimmed">
                          {compact.format(m.prompt_tokens)} / {compact.format(m.completion_tokens)}
                        </Text>
                      </Table.Td>
                      <Table.Td>
                        <Group gap={4}>
                          {m.features.slice(0, 3).map((f) => (
                            <Tooltip
                              key={f.feature}
                              label={`${f.requests} requests · ${compact.format(f.total_tokens)} tokens · ${usd(f.cost_usd)}`}
                              withArrow
                            >
                              <Badge variant="light" color="gray" size="sm" tt="none">
                                {f.feature}
                              </Badge>
                            </Tooltip>
                          ))}
                        </Group>
                      </Table.Td>
                      <Table.Td>
                        <Text size="xs" c="dimmed">
                          {formatDate(m.last_used_at)}
                        </Text>
                      </Table.Td>
                    </Table.Tr>
                  );
                })}
                {report && report.members.length === 0 ? (
                  <Table.Tr>
                    <Table.Td colSpan={7}>
                      <Text ta="center" c="dimmed" py="md">
                        No AI usage recorded in the last {report.days} days. Usage is recorded from now on.
                      </Text>
                    </Table.Td>
                  </Table.Tr>
                ) : null}
              </Table.Tbody>
            </Table>
          </Box>
        </Paper>
      </Stack>
    </Container>
  );
}
