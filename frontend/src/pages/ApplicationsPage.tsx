import {
  ActionIcon,
  Alert,
  Anchor,
  Badge,
  Button,
  Container,
  Divider,
  Group,
  Paper,
  PasswordInput,
  Select,
  SimpleGrid,
  Stack,
  Table,
  Tabs,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { Dropzone } from "@mantine/dropzone";
import { useForm } from "@mantine/form";
import { notifications } from "@mantine/notifications";
import {
  IconBrowserPlus,
  IconCheck,
  IconExternalLink,
  IconPlus,
  IconRefresh,
  IconTrash,
  IconUpload,
} from "@tabler/icons-react";
import { useCallback, useEffect, useState } from "react";

import {
  APPLICATION_STATUSES,
  applicationsApi,
  extensionApi,
  resumeApi,
  type JobApplication,
} from "../auth/api";

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

function TrackerTab() {
  const [items, setItems] = useState<JobApplication[]>([]);
  const [stats, setStats] = useState<Record<string, number>>({});
  const [statusFilter, setStatusFilter] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [list, s] = await Promise.all([
        applicationsApi.list({ status: statusFilter || undefined, limit: 100 }),
        applicationsApi.stats(),
      ]);
      setItems(list.items);
      setStats(s.by_status);
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  useEffect(() => {
    load();
  }, [load]);

  const setStatus = async (id: string, status: string) => {
    const updated = await applicationsApi.update(id, { status });
    setItems((prev) => prev.map((it) => (it.id === id ? updated : it)));
    const s = await applicationsApi.stats();
    setStats(s.by_status);
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

      <Group>
        <Select
          placeholder="All statuses"
          clearable
          data={APPLICATION_STATUSES.map((s) => ({ value: s, label: s }))}
          value={statusFilter}
          onChange={setStatusFilter}
          w={200}
        />
        <Button variant="light" onClick={load} loading={loading}>
          Refresh
        </Button>
      </Group>

      {items.length === 0 ? (
        <Alert color="gray" variant="light">
          No applications tracked yet. Install the JobBot Copilot extension, then open a job posting on
          Greenhouse, Lever, or Workday.
        </Alert>
      ) : (
        <Table.ScrollContainer minWidth={720}>
          <Table striped highlightOnHover verticalSpacing="sm">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Role</Table.Th>
                <Table.Th>Company</Table.Th>
                <Table.Th>Source</Table.Th>
                <Table.Th>Status</Table.Th>
                <Table.Th>Added</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {items.map((it) => (
                <Table.Tr key={it.id}>
                  <Table.Td>
                    <Anchor href={it.job_url} target="_blank" size="sm" lineClamp={1}>
                      {it.job_title || it.job_url}
                    </Anchor>
                  </Table.Td>
                  <Table.Td>{it.company || "—"}</Table.Td>
                  <Table.Td>
                    <Badge variant="light" size="sm" tt="capitalize">
                      {it.ats}
                    </Badge>
                  </Table.Td>
                  <Table.Td>
                    <Select
                      size="xs"
                      w={140}
                      data={APPLICATION_STATUSES.map((s) => ({ value: s, label: s }))}
                      value={it.status}
                      onChange={(v) => v && setStatus(it.id, v)}
                      styles={{ input: { textTransform: "capitalize" } }}
                    />
                  </Table.Td>
                  <Table.Td>
                    <Text size="xs" c="dimmed">
                      {it.created_at ? new Date(it.created_at).toLocaleDateString() : "—"}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Badge color={STATUS_COLOR[it.status] || "gray"} variant="dot" size="sm" />
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}
    </Stack>
  );
}

const BOOL_OPTS = [
  { value: "", label: "Not set" },
  { value: "yes", label: "Yes" },
  { value: "no", label: "No" },
];

const EDUCATION_OPTS = [
  "High School Diploma",
  "Associate's Degree",
  "Bachelor's Degree",
  "Master's Degree",
  "Doctorate / PhD",
  "Other",
].map((v) => ({ value: v, label: v }));

function generatePassword(): string {
  const chars = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789!@#$%";
  const bytes = new Uint32Array(16);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => chars[b % chars.length]).join("");
}

const PROFILE_FIELDS = {
  first_name: "", last_name: "", phone: "", phone_country_code: "", phone_device_type: "",
  address: "", address_line2: "", city: "", state: "", postal_code: "", country: "",
  linkedin: "", github: "", portfolio: "",
  work_authorized: "", requires_sponsorship: "", currently_employed: "",
  willing_to_relocate: "", over_18: "", worked_here_before: "", has_drivers_license: "",
  desired_salary: "", notice_period_days: "", start_date: "",
  years_of_experience: "", highest_education: "", how_heard_about_us: "",
  application_password: "",
};

type CustomAnswer = { q: string; a: string };

function AutofillSetupTab() {
  const [hasResume, setHasResume] = useState(false);
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [hasSavedPassword, setHasSavedPassword] = useState(false);
  const [customAnswers, setCustomAnswers] = useState<CustomAnswer[]>([]);

  const form = useForm({ initialValues: PROFILE_FIELDS });

  useEffect(() => {
    extensionApi.getProfile().then((p) => {
      setHasResume(p.has_base_resume);
      const ap = p.autofill_profile as Record<string, unknown>;
      const bool = (v: unknown) => (v == null ? "" : v ? "yes" : "no");
      form.setValues({
        first_name: String(ap.first_name || ""),
        last_name: String(ap.last_name || ""),
        phone: String(ap.phone || ""),
        phone_country_code: String(ap.phone_country_code || ""),
        phone_device_type: String(ap.phone_device_type || ""),
        address: String(ap.address || ""),
        address_line2: String(ap.address_line2 || ""),
        city: String(ap.city || ""),
        state: String(ap.state || ""),
        postal_code: String(ap.postal_code || ""),
        country: String(ap.country || ""),
        linkedin: String(ap.linkedin || ""),
        github: String(ap.github || ""),
        portfolio: String(ap.portfolio || ""),
        work_authorized: bool(ap.work_authorized),
        requires_sponsorship: bool(ap.requires_sponsorship),
        currently_employed: bool(ap.currently_employed),
        willing_to_relocate: bool(ap.willing_to_relocate),
        over_18: bool(ap.over_18),
        worked_here_before: bool(ap.worked_here_before),
        has_drivers_license: bool(ap.has_drivers_license),
        desired_salary: String(ap.desired_salary || ""),
        notice_period_days: String(ap.notice_period_days || ""),
        start_date: String(ap.start_date || ""),
        years_of_experience: String(ap.years_of_experience || ""),
        highest_education: String(ap.highest_education || ""),
        how_heard_about_us: String(ap.how_heard_about_us || ""),
        application_password: "",
      });
      setHasSavedPassword(Boolean(ap.has_application_password));
      const answers = Array.isArray(ap.custom_answers) ? (ap.custom_answers as CustomAnswer[]) : [];
      setCustomAnswers(answers.length ? answers : []);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const boolKeys = [
    "work_authorized", "requires_sponsorship", "currently_employed",
    "willing_to_relocate", "over_18", "worked_here_before", "has_drivers_license",
  ] as const;

  const save = form.onSubmit(async (v) => {
    setSaving(true);
    try {
      const payload: Record<string, unknown> = { ...v };
      for (const key of boolKeys) {
        payload[key] = v[key] === "" ? null : v[key] === "yes";
      }
      payload.custom_answers = customAnswers.filter((c) => c.q.trim() && c.a.trim());
      const result = await extensionApi.saveProfile(payload);
      setHasSavedPassword(Boolean((result.autofill_profile as Record<string, unknown>).has_application_password));
      form.setFieldValue("application_password", "");
      notifications.show({ title: "Saved", message: "Autofill profile updated.", color: "teal" });
    } catch (e) {
      notifications.show({
        title: "Could not save",
        message: e instanceof Error ? e.message : "Try again.",
        color: "red",
      });
    } finally {
      setSaving(false);
    }
  });

  const onDrop = async (files: File[]) => {
    if (!files[0]) return;
    setUploading(true);
    try {
      await resumeApi.saveFromFile(files[0]);
      setHasResume(true);
      notifications.show({ title: "Base resume saved", message: files[0].name, color: "teal" });
    } catch (e) {
      notifications.show({
        title: "Upload failed",
        message: e instanceof Error ? e.message : "Try again.",
        color: "red",
      });
    } finally {
      setUploading(false);
    }
  };

  return (
    <Stack gap="lg" maw={680}>
      <Paper withBorder p="md" radius="md" bg="dark.7">
        <Group justify="space-between" mb="xs">
          <Text fw={600}>Base resume</Text>
          <Badge color={hasResume ? "teal" : "yellow"} variant="light">
            {hasResume ? "Saved" : "Not set"}
          </Badge>
        </Group>
        <Text size="sm" c="dimmed" mb="sm">
          Used by the extension for quick-fill and "Tailor for this job". Upload a .docx or .pdf.
        </Text>
        <Dropzone
          onDrop={onDrop}
          loading={uploading}
          maxSize={15 * 1024 ** 2}
          accept={["application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".pdf", ".docx"]}
        >
          <Group justify="center" gap="sm" mih={70} style={{ pointerEvents: "none" }}>
            <IconUpload size={22} />
            <div>
              <Text size="sm">Drop resume here</Text>
              <Text size="xs" c="dimmed">
                .docx or .pdf, max 15 MB
              </Text>
            </div>
          </Group>
        </Dropzone>
      </Paper>

      <form onSubmit={save}>
        <Stack gap="sm">
          <Text fw={600}>Contact &amp; address</Text>
          <Group grow>
            <TextInput label="First name" {...form.getInputProps("first_name")} />
            <TextInput label="Last name" {...form.getInputProps("last_name")} />
          </Group>
          <Group grow align="flex-end">
            <TextInput
              label="Phone"
              placeholder="555 123 4567"
              {...form.getInputProps("phone")}
            />
            <TextInput
              label="Country code"
              placeholder="+1"
              w={110}
              {...form.getInputProps("phone_country_code")}
            />
            <Select
              label="Phone type"
              placeholder="Mobile"
              data={["Mobile", "Home", "Work"]}
              {...form.getInputProps("phone_device_type")}
            />
          </Group>
          <Group grow>
            <TextInput label="Address line 1" {...form.getInputProps("address")} />
            <TextInput label="Address line 2 (apt/suite)" {...form.getInputProps("address_line2")} />
          </Group>
          <Group grow>
            <TextInput label="City" {...form.getInputProps("city")} />
            <TextInput label="State / region" {...form.getInputProps("state")} />
            <TextInput label="Postal / ZIP code" {...form.getInputProps("postal_code")} />
            <TextInput label="Country" {...form.getInputProps("country")} />
          </Group>
          <TextInput label="LinkedIn URL" {...form.getInputProps("linkedin")} />
          <Group grow>
            <TextInput label="GitHub URL" {...form.getInputProps("github")} />
            <TextInput label="Portfolio URL" {...form.getInputProps("portfolio")} />
          </Group>

          <Divider label="Common application questions" labelPosition="left" mt="sm" />
          <Group grow>
            <Select label="Authorized to work" data={BOOL_OPTS} {...form.getInputProps("work_authorized")} />
            <Select
              label="Needs visa sponsorship"
              data={BOOL_OPTS}
              {...form.getInputProps("requires_sponsorship")}
            />
          </Group>
          <Group grow>
            <Select label="Currently employed" data={BOOL_OPTS} {...form.getInputProps("currently_employed")} />
            <Select label="Willing to relocate" data={BOOL_OPTS} {...form.getInputProps("willing_to_relocate")} />
          </Group>
          <Group grow>
            <Select label="At least 18 years old" data={BOOL_OPTS} {...form.getInputProps("over_18")} />
            <Select
              label="Worked here before"
              data={BOOL_OPTS}
              {...form.getInputProps("worked_here_before")}
            />
            <Select
              label="Valid driver's license"
              data={BOOL_OPTS}
              {...form.getInputProps("has_drivers_license")}
            />
          </Group>
          <Group grow>
            <TextInput label="Years of experience" placeholder="5" {...form.getInputProps("years_of_experience")} />
            <Select
              label="Highest education"
              data={EDUCATION_OPTS}
              searchable
              {...form.getInputProps("highest_education")}
            />
          </Group>
          <TextInput
            label="How did you hear about us?"
            placeholder="LinkedIn, referral, job board…"
            {...form.getInputProps("how_heard_about_us")}
          />
          <Group grow>
            <TextInput label="Desired salary" {...form.getInputProps("desired_salary")} />
            <TextInput label="Notice period (days)" {...form.getInputProps("notice_period_days")} />
            <TextInput label="Available start date" {...form.getInputProps("start_date")} />
          </Group>

          <Divider label="Application account password" labelPosition="left" mt="sm" />
          <Text size="xs" c="dimmed">
            Some ATS platforms (Workday especially) require creating an account to apply. Set one
            password here to reuse for those — it is encrypted at rest and is separate from your
            JobBot sign-in password.
          </Text>
          <Group align="flex-end" gap="xs">
            <PasswordInput
              label="Application password"
              placeholder={hasSavedPassword ? "•••••••• (saved — leave blank to keep it)" : "Not set"}
              style={{ flex: 1 }}
              {...form.getInputProps("application_password")}
            />
            <ActionIcon
              variant="light"
              size="lg"
              title="Generate a strong password"
              onClick={() => form.setFieldValue("application_password", generatePassword())}
            >
              <IconRefresh size={16} />
            </ActionIcon>
          </Group>

          <Divider label="EEO / demographic (optional)" labelPosition="left" mt="sm" />
          <Text size="xs" c="dimmed">
            Left blank unless you set them — the extension defaults these to "decline to
            self-identify" rather than guessing.
          </Text>

          <Divider label="Custom questions & answers" labelPosition="left" mt="sm" />
          <Text size="xs" c="dimmed">
            Anything else a form regularly asks — the extension matches these by question text
            before falling back to an AI-drafted answer.
          </Text>
          <Stack gap="xs">
            {customAnswers.map((row, i) => (
              <Group key={i} align="flex-start" gap="xs" wrap="nowrap">
                <TextInput
                  placeholder="Question (as it appears on the form)"
                  value={row.q}
                  onChange={(e) => {
                    const next = [...customAnswers];
                    next[i] = { ...next[i], q: e.currentTarget.value };
                    setCustomAnswers(next);
                  }}
                  style={{ flex: 1 }}
                />
                <TextInput
                  placeholder="Your answer"
                  value={row.a}
                  onChange={(e) => {
                    const next = [...customAnswers];
                    next[i] = { ...next[i], a: e.currentTarget.value };
                    setCustomAnswers(next);
                  }}
                  style={{ flex: 1 }}
                />
                <ActionIcon
                  color="red"
                  variant="subtle"
                  mt={4}
                  onClick={() => setCustomAnswers(customAnswers.filter((_, idx) => idx !== i))}
                >
                  <IconTrash size={16} />
                </ActionIcon>
              </Group>
            ))}
            <Button
              variant="light"
              size="xs"
              w="fit-content"
              leftSection={<IconPlus size={14} />}
              onClick={() => setCustomAnswers([...customAnswers, { q: "", a: "" }])}
            >
              Add question
            </Button>
          </Stack>

          <Button type="submit" loading={saving} w="fit-content" leftSection={<IconCheck size={16} />} mt="sm">
            Save autofill profile
          </Button>
        </Stack>
      </form>
    </Stack>
  );
}

export default function ApplicationsPage() {
  return (
    <Container size="lg" py={{ base: "md", sm: "xl" }} px={{ base: "sm", md: "md" }}>
      <Stack gap="lg">
        <Group justify="space-between" wrap="wrap">
          <Title order={2}>Applications</Title>
          <Button
            variant="light"
            leftSection={<IconBrowserPlus size={16} />}
            rightSection={<IconExternalLink size={14} />}
            component="a"
            href="https://chromewebstore.google.com/"
            target="_blank"
          >
            Get the browser extension
          </Button>
        </Group>
        <Tabs defaultValue="tracker" keepMounted={false}>
          <Tabs.List mb="md">
            <Tabs.Tab value="tracker">Tracker</Tabs.Tab>
            <Tabs.Tab value="setup">Autofill setup</Tabs.Tab>
          </Tabs.List>
          <Tabs.Panel value="tracker">
            <TrackerTab />
          </Tabs.Panel>
          <Tabs.Panel value="setup">
            <AutofillSetupTab />
          </Tabs.Panel>
        </Tabs>
      </Stack>
    </Container>
  );
}
