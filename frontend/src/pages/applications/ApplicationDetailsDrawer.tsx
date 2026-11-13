import {
  ActionIcon,
  Alert,
  Anchor,
  Badge,
  Button,
  CopyButton,
  Divider,
  Drawer,
  FileButton,
  Group,
  Highlight,
  Loader,
  Paper,
  Stack,
  Text,
  Title,
  Tooltip,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import {
  IconCheck,
  IconCopy,
  IconDownload,
  IconExternalLink,
  IconFileText,
  IconPencil,
  IconUpload,
} from "@tabler/icons-react";
import { useEffect, useState } from "react";

import type { JobApplication, TrackerApi } from "../../auth/api";

const SOURCE_LABEL: Record<string, string> = {
  attached_by_extension: "Attached by JobBot",
  selected_on_page: "Picked on the application page",
  uploaded_manually: "Uploaded here",
};

// Statuses that an interview invitation moves forward.
const BEFORE_INTERVIEW = new Set(["detected", "drafting", "ready", "submitted", "assessment"]);

function formatSize(bytes: number): string {
  return bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

function CopyIcon({ value, label }: { value: string; label: string }) {
  return (
    <CopyButton value={value} timeout={1500}>
      {({ copied, copy }) => (
        <Tooltip label={copied ? "Copied" : label} withArrow>
          <ActionIcon variant="subtle" color={copied ? "teal" : "gray"} onClick={copy} aria-label={label}>
            {copied ? <IconCheck size={16} /> : <IconCopy size={16} />}
          </ActionIcon>
        </Tooltip>
      )}
    </CopyButton>
  );
}

type Props = {
  /** The row that was clicked (list payload — the full JD is fetched here). */
  application: JobApplication | null;
  api: TrackerApi;
  /** Words from the search box to highlight in the job description. */
  highlight?: string[];
  readOnly?: boolean;
  onClose: () => void;
  onChanged: (app: JobApplication) => void;
  onEdit: (app: JobApplication) => void;
};

/** Everything needed when an employer gets back to you: the posting link, the exact resume sent, the JD. */
export function ApplicationDetailsDrawer({ application, api, highlight = [], readOnly, onClose, onChanged, onEdit }: Props) {
  const [full, setFull] = useState<JobApplication | null>(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!application) {
      setFull(null);
      return;
    }
    let cancelled = false;
    setFull(application);
    setLoading(true);
    api
      .get(application.id)
      .then((a) => !cancelled && setFull({ ...a, match: application.match }))
      .catch((e) => notifications.show({ title: "Couldn't load details", message: (e as Error).message, color: "red" }))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [application, api]);

  const app = full;
  const appliedAt = app?.submitted_at || app?.created_at;
  const resume = app?.applied_resume;

  const apply = (updated: JobApplication) => {
    const merged = { ...updated, match: app?.match };
    setFull(merged);
    onChanged(merged);
  };

  const markInterviewing = async () => {
    if (!app) return;
    setBusy(true);
    try {
      apply(await api.update(app.id, { status: "interviewing" }));
    } catch (e) {
      notifications.show({ title: "Couldn't update status", message: (e as Error).message, color: "red" });
    } finally {
      setBusy(false);
    }
  };

  const uploadResume = async (file: File | null) => {
    if (!app || !file) return;
    setBusy(true);
    try {
      apply(await api.uploadResume(app.id, file));
    } catch (e) {
      notifications.show({ title: "Upload failed", message: (e as Error).message, color: "red" });
    } finally {
      setBusy(false);
    }
  };

  const download = () =>
    app &&
    api
      .downloadResume(app)
      .catch((e) => notifications.show({ title: "Download failed", message: (e as Error).message, color: "red" }));

  return (
    <Drawer
      opened={application != null}
      onClose={onClose}
      position="right"
      size="xl"
      title={<Text fw={600}>Application details</Text>}
    >
      {app && (
        <Stack gap="md">
          <div>
            <Title order={3}>{app.job_title || "Untitled role"}</Title>
            <Text c="dimmed">
              {[app.company, app.location].filter(Boolean).join(" · ") || "Company not recorded"}
            </Text>
            <Group gap="xs" mt={6}>
              <Badge variant="light" tt="capitalize">
                {app.status}
              </Badge>
              <Badge variant="outline" color="gray" tt="capitalize">
                {app.ats}
              </Badge>
              {appliedAt && (
                <Text size="sm" c="dimmed">
                  Applied{" "}
                  {new Date(appliedAt).toLocaleString(undefined, {
                    weekday: "short",
                    month: "short",
                    day: "numeric",
                    year: "numeric",
                    hour: "numeric",
                    minute: "2-digit",
                  })}
                </Text>
              )}
            </Group>
            {app.member && (
              <Text size="sm" c="dimmed" mt={4}>
                Member: {app.member.name || app.member.email}
              </Text>
            )}
          </div>

          {!readOnly && (
            <Group gap="xs">
              {BEFORE_INTERVIEW.has(app.status) && (
                <Button size="xs" color="grape" variant="light" loading={busy} onClick={markInterviewing}>
                  Mark as interviewing
                </Button>
              )}
              <Button size="xs" variant="default" leftSection={<IconPencil size={14} />} onClick={() => onEdit(app)}>
                Edit
              </Button>
            </Group>
          )}

          <Paper withBorder p="sm" radius="md">
            <Text size="xs" c="dimmed" fw={600} tt="uppercase" mb={4}>
              Job link
            </Text>
            <Group gap="xs" wrap="nowrap">
              <Anchor href={app.job_url} target="_blank" rel="noreferrer" size="sm" style={{ wordBreak: "break-all" }}>
                {app.job_url}
              </Anchor>
              <CopyIcon value={app.job_url} label="Copy link" />
              <Tooltip label="Open posting" withArrow>
                <ActionIcon
                  variant="subtle"
                  color="gray"
                  component="a"
                  href={app.job_url}
                  target="_blank"
                  rel="noreferrer"
                  aria-label="Open posting"
                >
                  <IconExternalLink size={16} />
                </ActionIcon>
              </Tooltip>
            </Group>
          </Paper>

          <Paper withBorder p="sm" radius="md">
            <Text size="xs" c="dimmed" fw={600} tt="uppercase" mb={4}>
              Resume you sent
            </Text>
            {resume ? (
              <Group justify="space-between" wrap="nowrap">
                <Group gap="xs" wrap="nowrap">
                  <IconFileText size={18} />
                  <div>
                    <Text size="sm" fw={500} lineClamp={1}>
                      {resume.filename}
                    </Text>
                    <Text size="xs" c="dimmed">
                      {SOURCE_LABEL[resume.source] || resume.source} · {formatSize(resume.size)}
                    </Text>
                  </div>
                </Group>
                <Button size="xs" leftSection={<IconDownload size={14} />} onClick={download}>
                  Download
                </Button>
              </Group>
            ) : (
              <Group justify="space-between">
                <Text size="sm" c="dimmed">
                  No resume was saved with this application.
                </Text>
                {!readOnly && (
                  <FileButton onChange={uploadResume} accept=".pdf,.doc,.docx,.rtf,.odt,.txt">
                    {(props) => (
                      <Button size="xs" variant="light" leftSection={<IconUpload size={14} />} loading={busy} {...props}>
                        Upload
                      </Button>
                    )}
                  </FileButton>
                )}
              </Group>
            )}
          </Paper>

          {app.notes && (
            <div>
              <Text size="xs" c="dimmed" fw={600} tt="uppercase" mb={4}>
                Notes
              </Text>
              <Text size="sm" style={{ whiteSpace: "pre-wrap" }}>
                {app.notes}
              </Text>
            </div>
          )}

          <Divider />

          <div>
            <Group justify="space-between" mb={6}>
              <Text size="xs" c="dimmed" fw={600} tt="uppercase">
                Job description
              </Text>
              {app.jd_text && <CopyIcon value={app.jd_text} label="Copy job description" />}
            </Group>
            {loading && app.jd_text == null ? (
              <Group gap="xs">
                <Loader size="xs" />
                <Text size="sm" c="dimmed">
                  Loading…
                </Text>
              </Group>
            ) : app.jd_text ? (
              <Highlight
                highlight={highlight}
                size="sm"
                style={{ whiteSpace: "pre-wrap", lineHeight: 1.6 }}
                highlightStyles={{ padding: "0 2px", borderRadius: 3 }}
              >
                {app.jd_text}
              </Highlight>
            ) : (
              <Alert color="gray" variant="light">
                The posting text wasn't captured for this application.{" "}
                {readOnly ? "Open the job link while it's still live." : "Open the job link while it's still live and paste the description in via Edit, so it's kept here and searchable."}
              </Alert>
            )}
          </div>
        </Stack>
      )}
    </Drawer>
  );
}
