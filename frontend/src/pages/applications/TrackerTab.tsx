import {
  ActionIcon,
  Alert,
  Anchor,
  Badge,
  Button,
  Group,
  Menu,
  Modal,
  Paper,
  Select,
  SimpleGrid,
  Stack,
  Table,
  Text,
  TextInput,
  Tooltip,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import {
  IconCalendar,
  IconDots,
  IconDownload,
  IconPencil,
  IconPlus,
  IconSearch,
  IconTrash,
} from "@tabler/icons-react";
import { Fragment, useCallback, useEffect, useMemo, useState } from "react";

import {
  APPLICATION_STATUSES,
  applicationsApi,
  type DateRange,
  type JobApplication,
  type TrackerApi,
} from "../../auth/api";
import { ApplicationFormModal } from "./ApplicationFormModal";

const STATUS_COLOR: Record<string, string> = {
  detected: "gray",
  drafting: "yellow",
  ready: "cyan",
  submitted: "teal",
  assessment: "orange",
  interviewing: "grape",
  offer: "green",
  rejected: "red",
  withdrawn: "dark",
};

const SOURCE_LABEL: Record<string, string> = {
  attached_by_extension: "Attached by JobBot",
  selected_on_page: "Picked on the application page",
  uploaded_manually: "Uploaded here",
};

const DATE_PRESETS = [
  { value: "today", label: "Today" },
  { value: "yesterday", label: "Yesterday" },
  { value: "7", label: "Last 7 days" },
  { value: "30", label: "Last 30 days" },
  { value: "month", label: "This month" },
  { value: "custom", label: "Pick dates…" },
];

/** YYYY-MM-DD of a local calendar day. */
function dayKey(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function daysAgo(n: number): Date {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d;
}

function presetRange(preset: string | null, from: string, to: string): DateRange {
  const today = dayKey(new Date());
  switch (preset) {
    case "today":
      return { date_from: today, date_to: today };
    case "yesterday":
      return { date_from: dayKey(daysAgo(1)), date_to: dayKey(daysAgo(1)) };
    case "7":
      return { date_from: dayKey(daysAgo(6)), date_to: today };
    case "30":
      return { date_from: dayKey(daysAgo(29)), date_to: today };
    case "month":
      return { date_from: `${today.slice(0, 8)}01`, date_to: today };
    case "custom":
      return { date_from: from || undefined, date_to: to || undefined };
    default:
      return {};
  }
}

/** When the job was applied: submitted, else added to the tracker. */
const appliedAt = (app: JobApplication) => app.submitted_at || app.created_at;

/** Rows grouped by the local day they were applied, newest day first. */
function groupByDay(items: JobApplication[]): { day: string; label: string; items: JobApplication[] }[] {
  const sorted = [...items].sort((a, b) => (appliedAt(b) || "").localeCompare(appliedAt(a) || ""));
  const groups = new Map<string, JobApplication[]>();
  for (const it of sorted) {
    const at = appliedAt(it);
    const day = at ? dayKey(new Date(at)) : "";
    groups.set(day, [...(groups.get(day) || []), it]);
  }
  const today = dayKey(new Date());
  const yesterday = dayKey(daysAgo(1));
  return Array.from(groups, ([day, rows]) => {
    const date = day ? new Date(`${day}T00:00:00`) : null;
    const name = date?.toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric", year: "numeric" });
    const label = !day ? "No date" : day === today ? `Today · ${name}` : day === yesterday ? `Yesterday · ${name}` : name!;
    return { day, label, items: rows };
  });
}

function formatSize(bytes: number): string {
  return bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

function ResumeCell({ app, api }: { app: JobApplication; api: TrackerApi }) {
  const r = app.applied_resume;
  if (!r) {
    return (
      <Text size="xs" c="dimmed">
        —
      </Text>
    );
  }
  return (
    <Tooltip label={`${SOURCE_LABEL[r.source] || r.source} · ${formatSize(r.size)}`} withArrow>
      <Anchor
        size="xs"
        lineClamp={1}
        maw={180}
        onClick={() =>
          api.downloadResume(app).catch((e) =>
            notifications.show({ title: "Download failed", message: (e as Error).message, color: "red" }),
          )
        }
      >
        <Group gap={4} wrap="nowrap">
          <IconDownload size={12} />
          {r.filename}
        </Group>
      </Anchor>
    </Tooltip>
  );
}

type TrackerProps = {
  /** Defaults to the signed-in member's own tracker. */
  api?: TrackerApi;
  /** Manager view: show whose tracker each job is in. */
  showMember?: boolean;
  /** When set, "Add application" is disabled with this explanation. */
  createDisabledReason?: string | null;
  emptyText?: string;
  /** Fires after any create/edit/delete (e.g. to refresh a summary elsewhere). */
  onChanged?: () => void;
  /** View only: no add/edit/delete/status changes (team members viewing their bidders). */
  readOnly?: boolean;
};

export function TrackerTab({
  api = applicationsApi,
  showMember = false,
  createDisabledReason = null,
  emptyText = "No applications tracked yet. With the JobBot Copilot extension installed, a job is tracked automatically when you submit an application and the site confirms it — or add one by hand.",
  onChanged,
  readOnly = false,
}: TrackerProps = {}) {
  const [items, setItems] = useState<JobApplication[]>([]);
  const [stats, setStats] = useState<Record<string, number>>({});
  const [statusFilter, setStatusFilter] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [datePreset, setDatePreset] = useState<string | null>(null);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<JobApplication | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [deleting, setDeleting] = useState<JobApplication | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);

  const range = useMemo(() => presetRange(datePreset, dateFrom, dateTo), [datePreset, dateFrom, dateTo]);
  const days = useMemo(() => groupByDay(items), [items]);

  const load = useCallback(
    async (quiet = false) => {
      if (!quiet) setLoading(true);
      try {
        const [list, s] = await Promise.all([
          api.list({ status: statusFilter || undefined, q: query.trim() || undefined, limit: 200, ...range }),
          api.stats(range),
        ]);
        setItems(list.items);
        setStats(s.by_status);
        setTotal(s.total);
      } catch (e) {
        notifications.show({ title: "Couldn't load applications", message: (e as Error).message, color: "red" });
      } finally {
        setLoading(false);
      }
    },
    [api, statusFilter, query, range],
  );

  useEffect(() => {
    const t = window.setTimeout(() => load(), query ? 300 : 0);
    return () => window.clearTimeout(t);
  }, [load, query]);

  const refreshStats = () => {
    api.stats(range).then((s) => {
      setStats(s.by_status);
      setTotal(s.total);
    });
    onChanged?.();
  };

  const upsertLocal = (app: JobApplication) => {
    setItems((prev) => (prev.some((it) => it.id === app.id) ? prev.map((it) => (it.id === app.id ? app : it)) : [app, ...prev]));
    refreshStats();
  };

  const setStatus = async (id: string, status: string) => {
    try {
      upsertLocal(await api.update(id, { status }));
    } catch (e) {
      notifications.show({ title: "Couldn't update status", message: (e as Error).message, color: "red" });
    }
  };

  const removeResume = async (app: JobApplication) => {
    try {
      upsertLocal(await api.removeResume(app.id));
    } catch (e) {
      notifications.show({ title: "Couldn't remove resume", message: (e as Error).message, color: "red" });
    }
  };

  const confirmDelete = async () => {
    if (!deleting) return;
    setDeleteBusy(true);
    try {
      await api.remove(deleting.id);
      setItems((prev) => prev.filter((it) => it.id !== deleting.id));
      refreshStats();
      setDeleting(null);
    } catch (e) {
      notifications.show({ title: "Couldn't delete", message: (e as Error).message, color: "red" });
    } finally {
      setDeleteBusy(false);
    }
  };

  return (
    <Stack gap="md">
      <SimpleGrid cols={{ base: 2, sm: 4 }} spacing="xs">
        {APPLICATION_STATUSES.filter((s) => stats[s]).map((s) => (
          <Paper key={s} withBorder p="xs" radius="md" bg="dark.7">
            <Text size="xs" c="dimmed" tt="capitalize">
              {s}
            </Text>
            <Text fw={700} size="lg">
              {stats[s]}
            </Text>
          </Paper>
        ))}
      </SimpleGrid>

      <Group justify="space-between" wrap="wrap">
        <Group wrap="wrap">
          <TextInput
            placeholder="Search role, company, URL…"
            leftSection={<IconSearch size={14} />}
            value={query}
            onChange={(e) => setQuery(e.currentTarget.value)}
            w={240}
          />
          <Select
            placeholder="All statuses"
            clearable
            data={APPLICATION_STATUSES.map((s) => ({ value: s, label: s }))}
            value={statusFilter}
            onChange={setStatusFilter}
            w={170}
          />
          <Select
            placeholder="All dates"
            clearable
            leftSection={<IconCalendar size={14} />}
            data={DATE_PRESETS}
            value={datePreset}
            onChange={setDatePreset}
            w={170}
          />
          {datePreset === "custom" && (
            <>
              <TextInput
                type="date"
                aria-label="Applied from"
                value={dateFrom}
                max={dateTo || undefined}
                onChange={(e) => setDateFrom(e.currentTarget.value)}
                w={150}
              />
              <Text size="sm" c="dimmed">
                to
              </Text>
              <TextInput
                type="date"
                aria-label="Applied to"
                value={dateTo}
                min={dateFrom || undefined}
                onChange={(e) => setDateTo(e.currentTarget.value)}
                w={150}
              />
            </>
          )}
          <Button variant="light" onClick={() => load()} loading={loading}>
            Refresh
          </Button>
        </Group>
        {!readOnly && (
          <Tooltip label={createDisabledReason} disabled={!createDisabledReason} withArrow>
            <Button
              leftSection={<IconPlus size={16} />}
              disabled={!!createDisabledReason}
              onClick={() => {
                setEditing(null);
                setFormOpen(true);
              }}
            >
              Add application
            </Button>
          </Tooltip>
        )}
      </Group>

      {(range.date_from || range.date_to) && !loading && (
        <Text size="sm" c="dimmed">
          {total} application{total === 1 ? "" : "s"} applied{" "}
          {range.date_from === range.date_to
            ? `on ${new Date(`${range.date_from}T00:00:00`).toLocaleDateString()}`
            : [
                range.date_from && `from ${new Date(`${range.date_from}T00:00:00`).toLocaleDateString()}`,
                range.date_to && `to ${new Date(`${range.date_to}T00:00:00`).toLocaleDateString()}`,
              ]
                .filter(Boolean)
                .join(" ")}
          .
        </Text>
      )}

      {items.length === 0 && !loading ? (
        <Alert color="gray" variant="light">
          {query || statusFilter || range.date_from || range.date_to
            ? "No applications match these filters."
            : emptyText}
        </Alert>
      ) : (
        <Table.ScrollContainer minWidth={860}>
          <Table striped highlightOnHover verticalSpacing="sm">
            <Table.Thead>
              <Table.Tr>
                {showMember && <Table.Th>Member</Table.Th>}
                <Table.Th>Role</Table.Th>
                <Table.Th>Company</Table.Th>
                <Table.Th>Status</Table.Th>
                <Table.Th>Applied</Table.Th>
                <Table.Th>Resume</Table.Th>
                <Table.Th w={40} />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {days.map((group) => (
                <Fragment key={group.day || "none"}>
                  <Table.Tr bg="dark.6">
                    <Table.Td colSpan={showMember ? 7 : 6}>
                      <Group gap="xs">
                        <IconCalendar size={14} />
                        <Text size="sm" fw={600}>
                          {group.label}
                        </Text>
                        <Badge variant="light" size="sm">
                          {group.items.length}
                        </Badge>
                      </Group>
                    </Table.Td>
                  </Table.Tr>
                  {group.items.map((it) => (
                    <Table.Tr key={it.id}>
                      {showMember && (
                        <Table.Td maw={200}>
                          <Text size="sm" fw={500} lineClamp={1}>
                            {it.member?.name || it.member?.email || "—"}
                          </Text>
                          {it.member?.name && (
                            <Text size="xs" c="dimmed" lineClamp={1}>
                              {it.member.email}
                            </Text>
                          )}
                        </Table.Td>
                      )}
                      <Table.Td maw={260}>
                        <Anchor href={it.job_url} target="_blank" size="sm" lineClamp={1}>
                          {it.job_title || it.job_url}
                        </Anchor>
                        <Group gap={6}>
                          <Badge variant="light" size="xs" tt="capitalize">
                            {it.ats}
                          </Badge>
                          {it.location && (
                            <Text size="xs" c="dimmed" lineClamp={1}>
                              {it.location}
                            </Text>
                          )}
                        </Group>
                      </Table.Td>
                      <Table.Td>{it.company || "—"}</Table.Td>
                      <Table.Td>
                        {readOnly ? (
                          <Badge color={STATUS_COLOR[it.status] || "gray"} variant="light" tt="capitalize">
                            {it.status}
                          </Badge>
                        ) : (
                          <Select
                            size="xs"
                            w={140}
                            data={APPLICATION_STATUSES.map((s) => ({ value: s, label: s }))}
                            value={it.status}
                            allowDeselect={false}
                            onChange={(v) => v && setStatus(it.id, v)}
                            leftSection={<Badge color={STATUS_COLOR[it.status] || "gray"} variant="dot" size="xs" p={0} />}
                            styles={{ input: { textTransform: "capitalize" } }}
                          />
                        )}
                      </Table.Td>
                      <Table.Td>
                        <Text size="xs" c="dimmed">
                          {appliedAt(it)
                            ? new Date(appliedAt(it)!).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })
                            : "—"}
                        </Text>
                      </Table.Td>
                      <Table.Td>
                        <ResumeCell app={it} api={api} />
                      </Table.Td>
                      <Table.Td>
                        {!readOnly && (
                          <Menu position="bottom-end" withinPortal>
                            <Menu.Target>
                              <ActionIcon variant="subtle" aria-label="Actions">
                                <IconDots size={16} />
                              </ActionIcon>
                            </Menu.Target>
                            <Menu.Dropdown>
                              <Menu.Item
                                leftSection={<IconPencil size={14} />}
                                onClick={() => {
                                  setEditing(it);
                                  setFormOpen(true);
                                }}
                              >
                                Edit
                              </Menu.Item>
                              {it.applied_resume && (
                                <Menu.Item leftSection={<IconTrash size={14} />} onClick={() => removeResume(it)}>
                                  Remove resume
                                </Menu.Item>
                            )}
                            <Menu.Divider />
                            <Menu.Item color="red" leftSection={<IconTrash size={14} />} onClick={() => setDeleting(it)}>
                              Delete application
                            </Menu.Item>
                          </Menu.Dropdown>
                        </Menu>
                        )}
                      </Table.Td>
                    </Table.Tr>
                  ))}
                </Fragment>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}

      <ApplicationFormModal
        opened={formOpen}
        application={editing}
        api={api}
        onClose={() => setFormOpen(false)}
        onSaved={upsertLocal}
      />

      <Modal opened={deleting != null} onClose={() => setDeleting(null)} title="Delete application?" size="sm">
        <Stack gap="md">
          <Text size="sm">
            Remove <b>{deleting?.job_title || deleting?.job_url}</b>
            {deleting?.company ? ` at ${deleting.company}` : ""} from{" "}
            {showMember && deleting?.member ? `${deleting.member.name || deleting.member.email}'s` : "your"} tracker? Its
            saved resume is deleted too.
          </Text>
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setDeleting(null)}>
              Cancel
            </Button>
            <Button color="red" loading={deleteBusy} onClick={confirmDelete}>
              Delete
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}
