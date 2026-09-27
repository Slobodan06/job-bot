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
  IconDots,
  IconDownload,
  IconPencil,
  IconPlus,
  IconSearch,
  IconTrash,
} from "@tabler/icons-react";
import { useCallback, useEffect, useState } from "react";

import { APPLICATION_STATUSES, applicationsApi, type JobApplication } from "../../auth/api";
import { ApplicationFormModal } from "./ApplicationFormModal";

const STATUS_COLOR: Record<string, string> = {
  detected: "gray",
  drafting: "yellow",
  ready: "cyan",
  submitted: "teal",
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

function formatSize(bytes: number): string {
  return bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

function ResumeCell({ app }: { app: JobApplication }) {
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
          applicationsApi.downloadResume(app).catch((e) =>
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

export function TrackerTab() {
  const [items, setItems] = useState<JobApplication[]>([]);
  const [stats, setStats] = useState<Record<string, number>>({});
  const [statusFilter, setStatusFilter] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<JobApplication | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [deleting, setDeleting] = useState<JobApplication | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);

  const load = useCallback(
    async (quiet = false) => {
      if (!quiet) setLoading(true);
      try {
        const [list, s] = await Promise.all([
          applicationsApi.list({ status: statusFilter || undefined, q: query.trim() || undefined, limit: 200 }),
          applicationsApi.stats(),
        ]);
        setItems(list.items);
        setStats(s.by_status);
      } catch (e) {
        notifications.show({ title: "Couldn't load applications", message: (e as Error).message, color: "red" });
      } finally {
        setLoading(false);
      }
    },
    [statusFilter, query],
  );

  useEffect(() => {
    const t = window.setTimeout(() => load(), query ? 300 : 0);
    return () => window.clearTimeout(t);
  }, [load, query]);

  const refreshStats = () => applicationsApi.stats().then((s) => setStats(s.by_status));

  const upsertLocal = (app: JobApplication) => {
    setItems((prev) => (prev.some((it) => it.id === app.id) ? prev.map((it) => (it.id === app.id ? app : it)) : [app, ...prev]));
    refreshStats();
  };

  const setStatus = async (id: string, status: string) => {
    try {
      upsertLocal(await applicationsApi.update(id, { status }));
    } catch (e) {
      notifications.show({ title: "Couldn't update status", message: (e as Error).message, color: "red" });
    }
  };

  const removeResume = async (app: JobApplication) => {
    try {
      upsertLocal(await applicationsApi.removeResume(app.id));
    } catch (e) {
      notifications.show({ title: "Couldn't remove resume", message: (e as Error).message, color: "red" });
    }
  };

  const confirmDelete = async () => {
    if (!deleting) return;
    setDeleteBusy(true);
    try {
      await applicationsApi.remove(deleting.id);
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
          <Button variant="light" onClick={() => load()} loading={loading}>
            Refresh
          </Button>
        </Group>
        <Button
          leftSection={<IconPlus size={16} />}
          onClick={() => {
            setEditing(null);
            setFormOpen(true);
          }}
        >
          Add application
        </Button>
      </Group>

      {items.length === 0 && !loading ? (
        <Alert color="gray" variant="light">
          {query || statusFilter
            ? "No applications match these filters."
            : "No applications tracked yet. With the JobBot Copilot extension installed, a job is tracked automatically when you submit an application and the site confirms it — or add one by hand."}
        </Alert>
      ) : (
        <Table.ScrollContainer minWidth={860}>
          <Table striped highlightOnHover verticalSpacing="sm">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Role</Table.Th>
                <Table.Th>Company</Table.Th>
                <Table.Th>Status</Table.Th>
                <Table.Th>Applied</Table.Th>
                <Table.Th>Resume</Table.Th>
                <Table.Th w={40} />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {items.map((it) => (
                <Table.Tr key={it.id}>
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
                  </Table.Td>
                  <Table.Td>
                    <Text size="xs" c="dimmed">
                      {it.submitted_at || it.created_at
                        ? new Date((it.submitted_at || it.created_at)!).toLocaleDateString()
                        : "—"}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <ResumeCell app={it} />
                  </Table.Td>
                  <Table.Td>
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
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}

      <ApplicationFormModal
        opened={formOpen}
        application={editing}
        onClose={() => setFormOpen(false)}
        onSaved={upsertLocal}
      />

      <Modal opened={deleting != null} onClose={() => setDeleting(null)} title="Delete application?" size="sm">
        <Stack gap="md">
          <Text size="sm">
            Remove <b>{deleting?.job_title || deleting?.job_url}</b>
            {deleting?.company ? ` at ${deleting.company}` : ""} from your tracker? Its saved resume is deleted
            too.
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
