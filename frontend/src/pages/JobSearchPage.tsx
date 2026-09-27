import {
  ActionIcon,
  Alert,
  Anchor,
  Badge,
  Button,
  Card,
  Container,
  Group,
  Loader,
  Select,
  Stack,
  Switch,
  Table,
  Tabs,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { IconExternalLink, IconKey, IconRefresh, IconSearch, IconTrash } from "@tabler/icons-react";
import { useCallback, useEffect, useState } from "react";

import { useAuth } from "../auth/AuthContext";
import {
  ApiKeyRequiredError,
  jobBoardsApi,
  jobSearchApi,
  type JobBoard,
  type JobListing,
  type PlatformCredential,
} from "../auth/api";

const COUNTRIES = [
  { value: "us", label: "United States" },
  { value: "gb", label: "United Kingdom" },
  { value: "ca", label: "Canada" },
  { value: "au", label: "Australia" },
  { value: "de", label: "Germany" },
  { value: "fr", label: "France" },
  { value: "nl", label: "Netherlands" },
  { value: "ie", label: "Ireland" },
  { value: "in", label: "India" },
  { value: "sg", label: "Singapore" },
  { value: "rs", label: "Serbia" },
  { value: "es", label: "Spain" },
  { value: "pl", label: "Poland" },
  { value: "br", label: "Brazil" },
];

const POSTED_WITHIN_OPTIONS = [
  { value: "1", label: "Past 24 hours" },
  { value: "3", label: "Past 3 days" },
  { value: "7", label: "Past week" },
  { value: "30", label: "Past month" },
];

function timeAgo(iso: string | null): string {
  if (!iso) return "";
  const ms = Date.now() - new Date(iso).getTime();
  const hours = Math.floor(ms / 36e5);
  if (hours < 1) return "Just posted";
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function JobCard({ job }: { job: JobListing }) {
  return (
    <Card withBorder radius="md" p="md">
      <Group justify="space-between" align="flex-start" wrap="nowrap">
        <Stack gap={4} style={{ flex: 1, minWidth: 0 }}>
          <Anchor href={job.url} target="_blank" rel="noopener noreferrer" fw={600} lineClamp={1}>
            {job.title || "Untitled role"}
          </Anchor>
          <Text size="sm" c="dimmed" lineClamp={1}>
            {job.company || "Unknown company"}
            {job.location ? ` · ${job.location}` : ""}
          </Text>
          <Group gap="xs" mt={4}>
            {job.remote ? (
              <Badge color="teal" variant="light" size="sm">
                Remote
              </Badge>
            ) : null}
            {job.employment_type ? (
              <Badge color="gray" variant="light" size="sm" tt="capitalize">
                {job.employment_type.toLowerCase().replace(/_/g, " ")}
              </Badge>
            ) : null}
            {job.source ? (
              <Badge color="blue" variant="light" size="sm" tt="capitalize">
                {job.source}
              </Badge>
            ) : null}
            {job.posted_at ? (
              <Text size="xs" c="dimmed">
                {timeAgo(job.posted_at)}
              </Text>
            ) : null}
          </Group>
          {job.description_snippet ? (
            <Text size="sm" c="dimmed" lineClamp={2} mt={4}>
              {job.description_snippet}
            </Text>
          ) : null}
        </Stack>
        <Button
          component="a"
          href={job.url}
          target="_blank"
          rel="noopener noreferrer"
          variant="light"
          size="sm"
          rightSection={<IconExternalLink size={14} />}
        >
          Apply
        </Button>
      </Group>
    </Card>
  );
}

function LiveSearchTab() {
  const [keyword, setKeyword] = useState("");
  const [country, setCountry] = useState("us");
  const [remoteOnly, setRemoteOnly] = useState(true);
  const [postedWithinDays, setPostedWithinDays] = useState("1");
  const [page, setPage] = useState(1);
  const [items, setItems] = useState<JobListing[]>([]);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);
  const [error, setError] = useState("");

  const runSearch = async (nextPage = 1) => {
    if (!keyword.trim()) {
      setError("Enter a keyword, e.g. \"Software Engineer\".");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const result = await jobSearchApi.search({
        keyword: keyword.trim(),
        country,
        remote: remoteOnly,
        posted_within_days: Number(postedWithinDays),
        page: nextPage,
      });
      setItems(nextPage === 1 ? result.items : (prev) => [...prev, ...result.items]);
      setPage(nextPage);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not search jobs. Try again.");
    } finally {
      setLoading(false);
      setSearched(true);
    }
  };

  return (
    <Stack gap="lg">
      <Card withBorder radius="md" p="md">
        <Stack gap="sm">
          <Group grow align="flex-end" wrap="wrap">
            <TextInput
              label="Keyword"
              placeholder="Software Engineer, AI Engineer…"
              value={keyword}
              onChange={(e) => setKeyword(e.currentTarget.value)}
              onKeyDown={(e) => e.key === "Enter" && runSearch(1)}
            />
            <Select
              label="Country"
              data={COUNTRIES}
              searchable
              value={country}
              onChange={(v) => v && setCountry(v)}
            />
            <Select
              label="Posted"
              data={POSTED_WITHIN_OPTIONS}
              value={postedWithinDays}
              onChange={(v) => v && setPostedWithinDays(v)}
            />
          </Group>
          <Group justify="space-between" wrap="wrap">
            <Switch
              label="Remote only"
              checked={remoteOnly}
              onChange={(e) => setRemoteOnly(e.currentTarget.checked)}
            />
            <Button
              leftSection={<IconSearch size={16} />}
              onClick={() => runSearch(1)}
              loading={loading}
            >
              Search
            </Button>
          </Group>
        </Stack>
      </Card>

      {error ? (
        <Alert color="red" variant="light">
          {error}
        </Alert>
      ) : null}

      {loading && items.length === 0 ? (
        <Group justify="center" py="xl">
          <Loader color="teal" />
        </Group>
      ) : null}

      {!loading && searched && items.length === 0 && !error ? (
        <Alert color="gray" variant="light">
          No jobs found for that search. Try a broader keyword or a longer posting window.
        </Alert>
      ) : null}

      {items.length > 0 ? (
        <Stack gap="sm">
          <Text size="sm" c="dimmed">
            {items.length} result{items.length === 1 ? "" : "s"} · sorted by most recent
          </Text>
          {items.map((job, i) => (
            <JobCard key={`${job.url}-${i}`} job={job} />
          ))}
          <Group justify="center" mt="sm">
            <Button variant="light" onClick={() => runSearch(page + 1)} loading={loading}>
              Load more
            </Button>
          </Group>
        </Stack>
      ) : null}
    </Stack>
  );
}

function AddApiKeyPrompt({
  request,
  onSaved,
  onCancel,
}: {
  request: { platform: string; label: string; message: string; signupUrl: string; signupNote: string };
  onSaved: () => void;
  onCancel: () => void;
}) {
  const [apiKey, setApiKey] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const save = async () => {
    if (!apiKey.trim()) {
      setError("Enter an API key.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      await jobBoardsApi.setPlatformCredential(request.platform, apiKey.trim());
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save that key.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Alert color="yellow" variant="light" title={`${request.label} needs an API key`} icon={<IconKey size={16} />}>
      <Stack gap="xs">
        <Text size="sm">{request.message}</Text>
        {request.signupUrl ? (
          <Text size="sm">
            Get a key here:{" "}
            <Anchor href={request.signupUrl} target="_blank" rel="noopener noreferrer">
              {request.signupUrl}
            </Anchor>
            {request.signupNote ? ` — ${request.signupNote}` : ""}
          </Text>
        ) : null}
        <Group align="flex-end" wrap="wrap">
          <TextInput
            placeholder={`${request.label} API key`}
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.currentTarget.value)}
            onKeyDown={(e) => e.key === "Enter" && save()}
            style={{ flex: 1, minWidth: 220 }}
          />
          <Button size="sm" onClick={save} loading={saving}>
            Save &amp; retry
          </Button>
          <Button size="sm" variant="subtle" onClick={onCancel}>
            Cancel
          </Button>
        </Group>
        {error ? (
          <Text size="xs" c="red">
            {error}
          </Text>
        ) : null}
      </Stack>
    </Alert>
  );
}

function PlatformCredentialsPanel({ credentials, onChange }: { credentials: PlatformCredential[]; onChange: () => void }) {
  if (credentials.length === 0) return null;
  return (
    <Card withBorder radius="md" p="md">
      <Stack gap="xs">
        <Text fw={600} size="sm">
          Keyed platform API keys
        </Text>
        {credentials.map((c) => (
          <Stack key={c.platform} gap={4}>
            <Group justify="space-between">
              <Group gap="xs">
                <Text size="sm">{c.label}</Text>
                <Badge color={c.has_key ? "teal" : "gray"} variant="light" size="sm">
                  {c.has_key ? "Key saved" : "No key"}
                </Badge>
              </Group>
              {c.has_key ? (
                <Button
                  size="xs"
                  variant="subtle"
                  color="red"
                  onClick={async () => {
                    await jobBoardsApi.removePlatformCredential(c.platform);
                    onChange();
                  }}
                >
                  Remove key
                </Button>
              ) : null}
            </Group>
            {!c.has_key && c.signup_url ? (
              <Text size="xs" c="dimmed">
                Get a key:{" "}
                <Anchor href={c.signup_url} target="_blank" rel="noopener noreferrer" size="xs">
                  {c.signup_url}
                </Anchor>
                {c.signup_note ? ` — ${c.signup_note}` : ""}
              </Text>
            ) : null}
          </Stack>
        ))}
      </Stack>
    </Card>
  );
}

function TrackedBoardsTab() {
  const { isOwner } = useAuth();
  const [boardUrl, setBoardUrl] = useState("");
  const [boards, setBoards] = useState<JobBoard[]>([]);
  const [jobs, setJobs] = useState<JobListing[]>([]);
  const [credentials, setCredentials] = useState<PlatformCredential[]>([]);
  const [adding, setAdding] = useState(false);
  const [loadingJobs, setLoadingJobs] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [keyRequest, setKeyRequest] = useState<
    { platform: string; label: string; message: string; signupUrl: string; signupNote: string } | null
  >(null);

  const load = useCallback(async () => {
    setLoadingJobs(true);
    try {
      const calls: [ReturnType<typeof jobBoardsApi.list>, ReturnType<typeof jobBoardsApi.listJobs>, Promise<{ items: PlatformCredential[] }>] = [
        jobBoardsApi.list(),
        jobBoardsApi.listJobs(),
        isOwner ? jobBoardsApi.listPlatformCredentials() : Promise.resolve({ items: [] }),
      ];
      const [boardList, jobList, credList] = await Promise.all(calls);
      setBoards(boardList.items);
      setJobs(jobList.items);
      setCredentials(credList.items);
    } finally {
      setLoadingJobs(false);
    }
  }, [isOwner]);

  useEffect(() => {
    load();
  }, [load]);

  const addBoard = async (urlOverride?: string) => {
    const target = (urlOverride ?? boardUrl).trim();
    if (!target) {
      setError("Paste a company job board link first.");
      return;
    }
    setAdding(true);
    setError("");
    setNotice("");
    setKeyRequest(null);
    try {
      const result = await jobBoardsApi.add(target);
      setNotice(
        `${result.board.company || result.board.platform}: added ${result.added_count} new job${
          result.added_count === 1 ? "" : "s"
        }` +
          (result.skipped_duplicate_count
            ? `, skipped ${result.skipped_duplicate_count} already saved`
            : "") +
          (result.filtered_out_count
            ? `, ${result.filtered_out_count} didn't match the filters (remote, posted in 24h, software, non-intern, non-federal)`
            : ""),
      );
      setBoardUrl("");
      await load();
    } catch (e) {
      if (e instanceof ApiKeyRequiredError) {
        setKeyRequest({
          platform: e.platform,
          label: e.label,
          message: e.message,
          signupUrl: e.signupUrl,
          signupNote: e.signupNote,
        });
      } else {
        // 422 = recognized-but-unsupported platform, or an unrecognized domain — surfaced as an alert.
        setError(e instanceof Error ? e.message : "Could not add that board. Try again.");
      }
    } finally {
      setAdding(false);
    }
  };

  const resync = async (board: JobBoard) => {
    setError("");
    setNotice("");
    try {
      const result = await jobBoardsApi.add(board.board_url);
      setNotice(`${board.company}: added ${result.added_count} new job${result.added_count === 1 ? "" : "s"}`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not resync that board.");
    }
  };

  const removeBoard = async (id: string) => {
    await jobBoardsApi.remove(id);
    await load();
  };

  return (
    <Stack gap="lg">
      {isOwner ? (
        <>
          <Card withBorder radius="md" p="md">
            <Stack gap="sm">
              <Text fw={600}>Track a company job board</Text>
              <Text size="sm" c="dimmed">
                Paste a specific company's board link (Greenhouse, Lever, Ashby, SmartRecruiters, or
                ZipRecruiter) — e.g. https://boards.greenhouse.io/yourcompany. Most platforms are
                pulled via a free public API (no key needed); a platform that requires a key (like
                ZipRecruiter) will prompt for one below. Jobs are filtered to remote / posted in the
                last 24h / software / non-intern / non-federal, and deduped against everything
                already saved. Only admins can add or remove sources — everyone on the team sees the
                results.
              </Text>
              <Group align="flex-end" wrap="wrap">
                <TextInput
                  placeholder="https://boards.greenhouse.io/yourcompany"
                  value={boardUrl}
                  onChange={(e) => setBoardUrl(e.currentTarget.value)}
                  onKeyDown={(e) => e.key === "Enter" && addBoard()}
                  style={{ flex: 1, minWidth: 260 }}
                />
                <Button onClick={() => addBoard()} loading={adding}>
                  Add &amp; sync
                </Button>
              </Group>
            </Stack>
          </Card>

          <PlatformCredentialsPanel credentials={credentials} onChange={load} />
        </>
      ) : (
        <Alert color="gray" variant="light">
          Job platform sources are managed by your admin. Matching jobs from every tracked source
          show up below.
        </Alert>
      )}

      {keyRequest ? (
        <AddApiKeyPrompt
          request={keyRequest}
          onCancel={() => setKeyRequest(null)}
          onSaved={async () => {
            const url = boardUrl;
            setKeyRequest(null);
            await addBoard(url);
          }}
        />
      ) : null}

      {error ? (
        <Alert color="red" variant="light" title="Couldn't add this board">
          {error}
        </Alert>
      ) : null}
      {notice ? (
        <Alert color="teal" variant="light">
          {notice}
        </Alert>
      ) : null}

      {isOwner && boards.length > 0 ? (
        <Table.ScrollContainer minWidth={640}>
          <Table striped highlightOnHover verticalSpacing="sm">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Company</Table.Th>
                <Table.Th>Platform</Table.Th>
                <Table.Th>Jobs saved</Table.Th>
                <Table.Th>Last synced</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {boards.map((b) => (
                <Table.Tr key={b.id}>
                  <Table.Td>
                    <Anchor href={b.board_url} target="_blank" size="sm">
                      {b.company || b.board_url}
                    </Anchor>
                  </Table.Td>
                  <Table.Td>
                    <Badge variant="light" size="sm" tt="capitalize">
                      {b.platform}
                    </Badge>
                  </Table.Td>
                  <Table.Td>{b.job_count}</Table.Td>
                  <Table.Td>
                    <Text size="xs" c="dimmed">
                      {b.last_synced_at ? new Date(b.last_synced_at).toLocaleString() : "—"}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Group gap={4} wrap="nowrap">
                      <ActionIcon variant="subtle" title="Resync" onClick={() => resync(b)}>
                        <IconRefresh size={16} />
                      </ActionIcon>
                      <ActionIcon
                        variant="subtle"
                        color="red"
                        title="Remove"
                        onClick={() => removeBoard(b.id)}
                      >
                        <IconTrash size={16} />
                      </ActionIcon>
                    </Group>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      ) : null}

      {loadingJobs ? (
        <Group justify="center" py="xl">
          <Loader color="teal" />
        </Group>
      ) : jobs.length === 0 ? (
        <Alert color="gray" variant="light">
          {isOwner
            ? "No saved jobs yet. Add a company board above — matching jobs (remote, posted in the last 24h, software, non-intern, non-federal) will show up here as they're found."
            : "No saved jobs yet. Once your admin tracks a company board, matching jobs will show up here."}
        </Alert>
      ) : (
        <Stack gap="sm">
          <Text size="sm" c="dimmed">
            {jobs.length} saved job{jobs.length === 1 ? "" : "s"} · sorted by most recent
          </Text>
          {jobs.map((job, i) => (
            <JobCard key={`${job.url}-${i}`} job={job} />
          ))}
        </Stack>
      )}
    </Stack>
  );
}

export default function JobSearchPage() {
  return (
    <Container size="lg" py={{ base: "md", sm: "xl" }} px={{ base: "sm", md: "md" }}>
      <Stack gap="lg">
        <Title order={2}>Job search</Title>
        <Text c="dimmed" size="sm">
          Search remote openings posted recently across the web, or track specific company job
          boards so nothing new slips by.
        </Text>

        <Tabs defaultValue="live" keepMounted={false}>
          <Tabs.List mb="md">
            <Tabs.Tab value="live">Live search</Tabs.Tab>
            <Tabs.Tab value="boards">Tracked boards</Tabs.Tab>
          </Tabs.List>
          <Tabs.Panel value="live">
            <LiveSearchTab />
          </Tabs.Panel>
          <Tabs.Panel value="boards">
            <TrackedBoardsTab />
          </Tabs.Panel>
        </Tabs>
      </Stack>
    </Container>
  );
}
