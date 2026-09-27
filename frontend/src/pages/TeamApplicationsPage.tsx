import {
  Badge,
  Box,
  Button,
  Container,
  Group,
  Paper,
  Select,
  Stack,
  Table,
  Text,
  Title,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconBriefcase, IconRefresh } from "@tabler/icons-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { adminApplicationsApi, adminTrackingApi, type MemberTrackingSummary } from "../auth/api";
import { TrackerTab } from "./applications/TrackerTab";

// Pipeline stages worth a column in the overview (everything else is in "Total").
const SUMMARY_STATUSES = ["submitted", "interviewing", "offer", "rejected"] as const;
const STATUS_COLOR: Record<string, string> = {
  submitted: "teal",
  interviewing: "grape",
  offer: "green",
  rejected: "red",
};

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(new Date(iso));
  } catch {
    return iso;
  }
}

/** Manager (owner) view of every member's application tracker. */
export default function TeamApplicationsPage() {
  const [params, setParams] = useSearchParams();
  const memberId = params.get("member");
  const [summary, setSummary] = useState<MemberTrackingSummary[]>([]);
  const [loading, setLoading] = useState(true);

  const loadSummary = useCallback(async () => {
    setLoading(true);
    try {
      setSummary(await adminTrackingApi.summary());
    } catch (e) {
      notifications.show({ title: "Could not load team summary", message: (e as Error).message, color: "red" });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadSummary();
  }, [loadSummary]);

  const selectMember = (id: string | null) => {
    const next = new URLSearchParams(params);
    if (id) next.set("member", id);
    else next.delete("member");
    setParams(next, { replace: true });
  };

  const api = useMemo(() => adminApplicationsApi(memberId), [memberId]);
  const selected = summary.find((row) => row.member.id === memberId) ?? null;
  const selectedLabel = selected ? selected.member.name || selected.member.email : null;
  const teamTotal = summary.reduce((sum, row) => sum + row.total, 0);

  return (
    <Container size="xl" py={{ base: "md", sm: "xl" }} px={{ base: "sm", md: "md" }}>
      <Stack gap="lg">
        <Group justify="space-between" align="flex-end" wrap="wrap">
          <Stack gap={4}>
            <Group gap="xs">
              <IconBriefcase size={24} stroke={1.5} />
              <Title order={2}>Team applications</Title>
            </Group>
            <Text c="dimmed" size="sm" maw={680}>
              Every member's tracked job applications. Pick a member to see, add, edit or delete their jobs and applied
              resumes — changes show up in their own tracker immediately.
            </Text>
          </Stack>
          <Button variant="light" color="teal" leftSection={<IconRefresh size={16} />} onClick={loadSummary} loading={loading}>
            Refresh
          </Button>
        </Group>

        <Paper withBorder radius="lg" bg="dark.7" style={{ overflow: "hidden" }}>
          <Box style={{ overflowX: "auto" }}>
            <Table highlightOnHover withTableBorder={false} verticalSpacing="sm">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Member</Table.Th>
                  <Table.Th ta="right">Total</Table.Th>
                  {SUMMARY_STATUSES.map((s) => (
                    <Table.Th key={s} ta="right" tt="capitalize">
                      {s}
                    </Table.Th>
                  ))}
                  <Table.Th>Last applied</Table.Th>
                  <Table.Th>Last activity</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {summary.map((row) => {
                  const active = row.member.id === memberId;
                  return (
                    <Table.Tr
                      key={row.member.id}
                      onClick={() => selectMember(active ? null : row.member.id)}
                      style={{ cursor: "pointer" }}
                      bg={active ? "var(--mantine-color-teal-light)" : undefined}
                    >
                      <Table.Td>
                        <Group gap={6} wrap="nowrap">
                          <div>
                            <Text fw={600} size="sm">
                              {row.member.name || "—"}
                            </Text>
                            <Text size="xs" c="dimmed">
                              {row.member.email}
                            </Text>
                          </div>
                          {row.role === "owner" && (
                            <Badge color="grape" variant="light" size="xs">
                              Owner
                            </Badge>
                          )}
                          {!row.has_access && (
                            <Badge color="yellow" variant="outline" size="xs">
                              No access
                            </Badge>
                          )}
                        </Group>
                      </Table.Td>
                      <Table.Td ta="right">
                        <Text fw={700} size="sm">
                          {row.total}
                        </Text>
                      </Table.Td>
                      {SUMMARY_STATUSES.map((s) => (
                        <Table.Td key={s} ta="right">
                          {row.by_status[s] ? (
                            <Badge color={STATUS_COLOR[s]} variant="light" size="sm">
                              {row.by_status[s]}
                            </Badge>
                          ) : (
                            <Text size="sm" c="dimmed">
                              0
                            </Text>
                          )}
                        </Table.Td>
                      ))}
                      <Table.Td>
                        <Text size="sm" c="dimmed">
                          {formatDate(row.last_applied_at)}
                        </Text>
                      </Table.Td>
                      <Table.Td>
                        <Text size="sm" c="dimmed">
                          {formatDate(row.last_activity_at)}
                        </Text>
                      </Table.Td>
                    </Table.Tr>
                  );
                })}
                {!loading && summary.length === 0 ? (
                  <Table.Tr>
                    <Table.Td colSpan={3 + SUMMARY_STATUSES.length + 1}>
                      <Text ta="center" c="dimmed" py="md">
                        No members yet.
                      </Text>
                    </Table.Td>
                  </Table.Tr>
                ) : null}
              </Table.Tbody>
            </Table>
          </Box>
        </Paper>

        <Stack gap="md">
          <Group justify="space-between" wrap="wrap" align="flex-end">
            <Title order={3} size="h4">
              {selectedLabel ? `${selectedLabel}'s applications` : `All applications (${teamTotal})`}
            </Title>
            <Select
              w={280}
              placeholder="All members"
              clearable
              searchable
              value={memberId}
              onChange={selectMember}
              data={summary.map((row) => ({
                value: row.member.id,
                label: `${row.member.name || row.member.email} (${row.total})`,
              }))}
            />
          </Group>
          <TrackerTab
            api={api}
            showMember={!memberId}
            createDisabledReason={memberId ? null : "Pick a member first — new jobs go into their tracker."}
            emptyText={selectedLabel ? `${selectedLabel} hasn't tracked any applications yet.` : "No member has tracked any applications yet."}
            onChanged={loadSummary}
          />
        </Stack>
      </Stack>
    </Container>
  );
}
