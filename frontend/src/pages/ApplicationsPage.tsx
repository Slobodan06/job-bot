import {
  ActionIcon,
  Alert,
  Button,
  Container,
  Divider,
  Group,
  PasswordInput,
  Select,
  Stack,
  Tabs,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { useForm } from "@mantine/form";
import { notifications } from "@mantine/notifications";
import {
  IconBrowserPlus,
  IconCheck,
  IconPlus,
  IconRefresh,
  IconTrash,
} from "@tabler/icons-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { extensionApi } from "../auth/api";
import { BaseResumeCard } from "../components/BaseResumeCard";
import { TrackerTab } from "./applications/TrackerTab";

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
  // Bidders see their team member's resume + autofill profile, read-only.
  const [readOnly, setReadOnly] = useState(false);
  const [ownerName, setOwnerName] = useState("");
  const [saving, setSaving] = useState(false);
  const [hasSavedPassword, setHasSavedPassword] = useState(false);
  const [customAnswers, setCustomAnswers] = useState<CustomAnswer[]>([]);

  const form = useForm({ initialValues: PROFILE_FIELDS });

  useEffect(() => {
    extensionApi.getProfile().then((p) => {
      setReadOnly(Boolean(p.read_only));
      setOwnerName(p.profile_owner_name || "");
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

  return (
    <Stack gap="lg" maw={680}>
      {readOnly && (
        <Alert color="blue" variant="light">
          You work from <b>{ownerName}</b>'s base resume and autofill profile. Only {ownerName} can change them — the
          extension fills applications with these details.
        </Alert>
      )}
      <BaseResumeCard />

      <form onSubmit={save}>
        {/* A disabled fieldset disables every input and button inside it. */}
        <fieldset disabled={readOnly} style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }}>
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

            {!readOnly && (
              <Button type="submit" loading={saving} w="fit-content" leftSection={<IconCheck size={16} />} mt="sm">
                Save autofill profile
              </Button>
            )}
          </Stack>
        </fieldset>
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
            component={Link}
            to="/download"
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
