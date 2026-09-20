import {
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
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { IconExternalLink, IconSearch } from "@tabler/icons-react";
import { useState } from "react";

import { jobSearchApi, type JobListing } from "../auth/api";

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
              <Badge color="blue" variant="light" size="sm">
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

export default function JobSearchPage() {
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
    <Container size="lg" py={{ base: "md", sm: "xl" }} px={{ base: "sm", md: "md" }}>
      <Stack gap="lg">
        <Title order={2}>Job search</Title>
        <Text c="dimmed" size="sm">
          Search remote openings posted recently across the web, then click through to apply.
        </Text>

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
    </Container>
  );
}
