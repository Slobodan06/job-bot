import { Alert, Badge, Button, Group, Paper, Skeleton, Stack, Text, Title } from "@mantine/core";
import { Dropzone } from "@mantine/dropzone";
import { notifications } from "@mantine/notifications";
import { IconInfoCircle, IconTrash, IconUpload } from "@tabler/icons-react";
import { useCallback, useEffect, useState } from "react";

import { resumeApi, type ResumeAccess } from "../auth/api";

const ACCEPT = [
  "application/pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  ".pdf",
  ".docx",
];

/**
 * The base resume: team members upload / replace / remove their own here (their assigned
 * bidders and the extension use it). Bidders see their team member's, read-only.
 */
export function BaseResumeCard({ onChange }: { onChange?: () => void }) {
  const [access, setAccess] = useState<ResumeAccess | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    resumeApi.access().then(setAccess).catch(() => setAccess(null));
  }, []);
  useEffect(load, [load]);

  const fail = (title: string, e: unknown) =>
    notifications.show({ title, message: e instanceof Error ? e.message : "Try again.", color: "red" });

  const upload = async (files: File[]) => {
    if (!files[0]) return;
    setBusy(true);
    try {
      await resumeApi.saveFromFile(files[0]);
      notifications.show({ title: "Base resume saved", message: files[0].name, color: "teal" });
      load();
      onChange?.();
    } catch (e) {
      fail("Upload failed", e);
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    setBusy(true);
    try {
      await resumeApi.remove();
      load();
      onChange?.();
    } catch (e) {
      fail("Couldn't remove", e);
    } finally {
      setBusy(false);
    }
  };

  if (!access) {
    return (
      <Paper withBorder radius="lg" p={{ base: "md", sm: "lg" }} bg="dark.7">
        <Skeleton h={90} />
      </Paper>
    );
  }

  const readOnly = access.uses_team_member_resume;
  const updated = access.base_resume_updated_at
    ? new Date(access.base_resume_updated_at).toLocaleDateString()
    : "";

  return (
    <Paper withBorder radius="lg" p={{ base: "md", sm: "lg" }} bg="dark.7">
      <Stack gap="sm">
        <Group justify="space-between" wrap="nowrap" align="flex-start">
          <div>
            <Title order={3} size="h4">
              {readOnly && access.team_member_name ? `${access.team_member_name}'s base resume` : "Base resume"}
            </Title>
            <Text size="sm" c="dimmed">
              {readOnly
                ? "You generate every resume, cover letter and answer from your team member's base resume. Only they can change it."
                : "Used when you don't upload a file, by the browser extension, and by the bidders assigned to you."}
            </Text>
          </div>
          <Badge color={access.has_base_resume ? "teal" : "yellow"} variant="light" style={{ flexShrink: 0 }}>
            {access.has_base_resume ? "Saved" : "Not set"}
          </Badge>
        </Group>

        {access.reason ? (
          <Alert color="yellow" variant="light" icon={<IconInfoCircle size={18} />}>
            {access.reason}
          </Alert>
        ) : access.has_base_resume ? (
          <Text size="sm">
            <Text span fw={600}>
              {access.base_resume_name || "Resume"}
            </Text>
            {updated ? (
              <Text span c="dimmed">
                {" "}
                · updated {updated}
              </Text>
            ) : null}
          </Text>
        ) : readOnly ? (
          <Alert color="yellow" variant="light" icon={<IconInfoCircle size={18} />}>
            {access.team_member_name || "Your team member"} hasn't uploaded a base resume yet — ask them to add it on
            their Profile page.
          </Alert>
        ) : null}

        {!readOnly ? (
          <>
            <Dropzone onDrop={upload} loading={busy} maxSize={15 * 1024 ** 2} accept={ACCEPT} multiple={false}>
              <Group justify="center" gap="sm" mih={64} style={{ pointerEvents: "none" }}>
                <IconUpload size={22} />
                <div>
                  <Text size="sm">{access.has_base_resume ? "Drop a new resume to replace it" : "Drop your resume here"}</Text>
                  <Text size="xs" c="dimmed">
                    .docx or .pdf, max 15 MB
                  </Text>
                </div>
              </Group>
            </Dropzone>
            {access.has_base_resume ? (
              <Button
                variant="subtle"
                color="red"
                size="xs"
                w="fit-content"
                leftSection={<IconTrash size={14} />}
                loading={busy}
                onClick={remove}
              >
                Remove base resume
              </Button>
            ) : null}
          </>
        ) : null}
      </Stack>
    </Paper>
  );
}
