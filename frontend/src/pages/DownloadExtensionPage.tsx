import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Code,
  Container,
  CopyButton,
  Group,
  Kbd,
  List,
  Paper,
  Skeleton,
  Stack,
  Text,
  ThemeIcon,
  Timeline,
  Title,
  Tooltip,
} from "@mantine/core";
import {
  IconAlertTriangle,
  IconBrandChrome,
  IconCheck,
  IconCopy,
  IconDownload,
  IconInfoCircle,
  IconLink,
  IconRefresh,
  IconShieldCheck,
} from "@tabler/icons-react";
import { useEffect, useState } from "react";

import { apiFetch } from "../auth/api";

type DownloadInfo = {
  available: boolean;
  name: string;
  version: string;
  filename: string;
  size: number;
  built_at: string;
};

const DOWNLOAD_URL = "/api/extension/download";

function formatSize(bytes: number): string {
  if (!bytes) return "";
  return bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : `${Math.round(bytes / 1024)} KB`;
}

function formatDate(iso: string): string {
  if (!iso) return "";
  try {
    return new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(new Date(iso));
  } catch {
    return "";
  }
}

/** Inline code with a copy button — chrome:// links can't be opened from a web page. */
function CopyCode({ value }: { value: string }) {
  return (
    <Group gap={4} wrap="nowrap" display="inline-flex" style={{ verticalAlign: "middle" }}>
      <Code>{value}</Code>
      <CopyButton value={value} timeout={1500}>
        {({ copied, copy }) => (
          <Tooltip label={copied ? "Copied" : "Copy"} withArrow>
            <ActionIcon size="sm" variant="subtle" color={copied ? "teal" : "gray"} onClick={copy} aria-label={`Copy ${value}`}>
              {copied ? <IconCheck size={14} /> : <IconCopy size={14} />}
            </ActionIcon>
          </Tooltip>
        )}
      </CopyButton>
    </Group>
  );
}

function Section({ title, icon, children }: { title: string; icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <Paper withBorder radius="lg" p={{ base: "md", sm: "lg" }} bg="dark.7">
      <Group gap="xs" mb="md">
        {icon}
        <Title order={3} size="h4">
          {title}
        </Title>
      </Group>
      {children}
    </Paper>
  );
}

export default function DownloadExtensionPage() {
  const [info, setInfo] = useState<DownloadInfo | null>(null);
  const [failed, setFailed] = useState(false);
  const shareLink = `${window.location.origin}/download`;

  useEffect(() => {
    apiFetch<DownloadInfo>("/api/extension/download/info")
      .then(setInfo)
      .catch(() => setFailed(true));
  }, []);

  const meta = info?.available
    ? [formatSize(info.size), info.built_at && `Updated ${formatDate(info.built_at)}`]
        .filter(Boolean)
        .join(" · ")
    : "";

  return (
    <Container size="md" py={{ base: "md", sm: "xl" }} px={{ base: "sm", md: "md" }}>
      <Stack gap="lg">
        <Stack gap={6}>
          <Group gap="xs">
            <ThemeIcon size={36} radius="md" variant="light" color="teal">
              <IconBrandChrome size={22} />
            </ThemeIcon>
            <Title order={2}>Download the JobBot Copilot Chrome extension</Title>
          </Group>
          <Text c="dimmed" size="sm" maw={680}>
            Detects job postings on any careers site, autofills applications with your resume, and tracks every
            application you submit in your JobBot account — together with the resume you sent.
          </Text>
        </Stack>

        <Paper withBorder radius="lg" p={{ base: "md", sm: "lg" }} shadow="sm">
          <Group justify="space-between" wrap="wrap" gap="md">
            <Stack gap={4}>
              <Group gap="xs">
                <Text fw={700} size="lg">
                  JobBot Copilot
                </Text>
                {info?.version ? (
                  <Badge variant="light" color="teal">
                    v{info.version}
                  </Badge>
                ) : null}
              </Group>
              {info == null && !failed ? (
                <Skeleton h={14} w={220} />
              ) : (
                <Text size="sm" c="dimmed">
                  {meta || "Chrome, Edge, Brave and other Chromium browsers"}
                </Text>
              )}
            </Stack>
            <Group gap="xs">
              <CopyButton value={shareLink} timeout={2000}>
                {({ copied, copy }) => (
                  <Button
                    variant="default"
                    leftSection={copied ? <IconCheck size={16} /> : <IconLink size={16} />}
                    onClick={copy}
                  >
                    {copied ? "Link copied" : "Copy share link"}
                  </Button>
                )}
              </CopyButton>
              <Button
                component="a"
                href={DOWNLOAD_URL}
                download
                size="md"
                leftSection={<IconDownload size={18} />}
                variant="gradient"
                gradient={{ from: "teal", to: "cyan", deg: 105 }}
                disabled={!info?.available}
              >
                Download .zip
              </Button>
            </Group>
          </Group>
          {(failed || (info && !info.available)) && (
            <Alert color="yellow" variant="light" mt="md" icon={<IconAlertTriangle size={18} />}>
              The extension package isn't available on this server right now. Please contact the site owner.
            </Alert>
          )}
        </Paper>

        <Section title="How to install" icon={<IconDownload size={20} />}>
          <Timeline active={6} bulletSize={26} lineWidth={2} color="teal">
            <Timeline.Item bullet={<Text size="xs" fw={700}>1</Text>} title="Download and unzip">
              <Text size="sm" c="dimmed">
                Download the zip and unzip it to a folder you will keep — <b>don't delete it</b>. Chrome runs the
                extension from that folder.
              </Text>
            </Timeline.Item>
            <Timeline.Item bullet={<Text size="xs" fw={700}>2</Text>} title="Open the extensions page">
              <Text size="sm" c="dimmed" component="div">
                In Chrome, open <CopyCode value="chrome://extensions" /> (paste it into the address bar). On Edge use{" "}
                <CopyCode value="edge://extensions" />.
              </Text>
            </Timeline.Item>
            <Timeline.Item bullet={<Text size="xs" fw={700}>3</Text>} title="Turn on Developer mode">
              <Text size="sm" c="dimmed">
                Flip the <b>Developer mode</b> switch in the top-right corner.
              </Text>
            </Timeline.Item>
            <Timeline.Item bullet={<Text size="xs" fw={700}>4</Text>} title="Click “Load unpacked”">
              <Text size="sm" c="dimmed">
                The button appears top-left once Developer mode is on.
              </Text>
            </Timeline.Item>
            <Timeline.Item bullet={<Text size="xs" fw={700}>5</Text>} title="Select the unzipped folder">
              <Text size="sm" c="dimmed" component="div">
                Choose the <Code>jobbot-copilot</Code> folder — the one that contains <Code>manifest.json</Code>.
              </Text>
            </Timeline.Item>
            <Timeline.Item bullet={<Text size="xs" fw={700}>6</Text>} title="Pin it and sign in">
              <Text size="sm" c="dimmed">
                Click the puzzle-piece icon in Chrome's toolbar and pin <b>JobBot Copilot</b>. Open it and sign in with
                your JobBot email and password. That's it — open any job posting to see it in action.
              </Text>
            </Timeline.Item>
          </Timeline>
        </Section>

        <Section title="Updating to a new version" icon={<IconRefresh size={20} />}>
          <List type="ordered" size="sm" spacing="xs">
            <List.Item>Download the latest zip from this page.</List.Item>
            <List.Item>
              Delete the contents of your <Code>jobbot-copilot</Code> folder and unzip the new files into the{" "}
              <b>same folder</b>.
            </List.Item>
            <List.Item>
              Open <CopyCode value="chrome://extensions" /> and click the reload icon (↻) on the JobBot Copilot card.
            </List.Item>
          </List>
          <Alert color="blue" variant="light" mt="md" icon={<IconInfoCircle size={18} />}>
            Please keep the extension on the latest version — older versions may stop autofilling or tracking
            applications correctly. You stay signed in when you update.
          </Alert>
        </Section>

        <Section title="Trouble installing?" icon={<IconAlertTriangle size={20} />}>
          <Stack gap="md">
            <div>
              <Text fw={600} size="sm" mb={4}>
                Chrome blocked the download
              </Text>
              <List size="sm" spacing={4} c="dimmed">
                <List.Item>
                  Open your downloads with <Kbd>Ctrl</Kbd> + <Kbd>J</Kbd> (<Kbd>⌘</Kbd> + <Kbd>Shift</Kbd> + <Kbd>J</Kbd>{" "}
                  on Mac).
                </List.Item>
                <List.Item>
                  Find <Code>{info?.filename || "jobbot-copilot.zip"}</Code> and choose <b>Keep</b> (or{" "}
                  <b>Keep anyway</b>).
                </List.Item>
              </List>
            </div>
            <div>
              <Text fw={600} size="sm" mb={4}>
                Windows won't unzip it, or files seem blocked
              </Text>
              <Text size="sm" c="dimmed">
                Right-click the zip → <b>Properties</b> → tick <b>Unblock</b> at the bottom → <b>OK</b>, then extract it
                again.
              </Text>
            </div>
            <div>
              <Text fw={600} size="sm" mb={4}>
                “Manifest file is missing or unreadable”
              </Text>
              <Text size="sm" c="dimmed">
                You selected the wrong folder. Select the inner <Code>jobbot-copilot</Code> folder that directly
                contains <Code>manifest.json</Code>.
              </Text>
            </div>
            <div>
              <Text fw={600} size="sm" mb={4}>
                The extension disappeared or shows an error
              </Text>
              <Text size="sm" c="dimmed">
                The unzipped folder was moved or deleted. Unzip it again to a permanent location and repeat “Load
                unpacked”.
              </Text>
            </div>
          </Stack>
        </Section>

        <Group gap="xs" wrap="nowrap" align="flex-start">
          <IconShieldCheck size={18} style={{ flexShrink: 0, marginTop: 2, opacity: 0.7 }} />
          <Text size="xs" c="dimmed">
            JobBot Copilot is shared as a zip installed in Developer mode rather than through the Chrome Web Store —
            that's expected. Only download it from this page, and check with your team lead if a link ever looks
            different. The extension never submits applications for you and does not run on LinkedIn.
          </Text>
        </Group>
      </Stack>
    </Container>
  );
}
