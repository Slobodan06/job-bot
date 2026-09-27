import { Button, FileInput, Group, Modal, Select, Stack, Text, TextInput, Textarea } from "@mantine/core";
import { useForm } from "@mantine/form";
import { notifications } from "@mantine/notifications";
import { IconFileText } from "@tabler/icons-react";
import { useEffect, useState } from "react";

import {
  APPLICATION_STATUSES,
  applicationsApi,
  type ApplicationInput,
  type JobApplication,
} from "../../auth/api";

type Props = {
  opened: boolean;
  /** null = create a new application */
  application: JobApplication | null;
  onClose: () => void;
  onSaved: (app: JobApplication) => void;
};

const toDateInput = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString("en-CA") : "");
// Local noon, so the calendar day never shifts across time zones.
const fromDateInput = (value: string) => (value ? new Date(`${value}T12:00:00`).toISOString() : null);

export function ApplicationFormModal({ opened, application, onClose, onSaved }: Props) {
  const isEdit = application != null;
  const [resumeFile, setResumeFile] = useState<File | null>(null);
  const [saving, setSaving] = useState(false);

  const form = useForm({
    initialValues: {
      job_url: "",
      job_title: "",
      company: "",
      location: "",
      status: "submitted",
      applied_on: "",
      notes: "",
    },
    validate: {
      job_url: (v: string) => (/^https?:\/\/\S+\.\S+/i.test(v.trim()) ? null : "Enter the job posting URL (https://…)"),
    },
  });

  useEffect(() => {
    if (!opened) return;
    setResumeFile(null);
    form.setValues({
      job_url: application?.job_url || "",
      job_title: application?.job_title || "",
      company: application?.company || "",
      location: application?.location || "",
      status: application?.status || "submitted",
      applied_on: toDateInput(application?.submitted_at ?? (application ? null : new Date().toISOString())),
      notes: application?.notes || "",
    });
    form.resetDirty();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opened, application]);

  const submit = form.onSubmit(async (v) => {
    setSaving(true);
    try {
      const body: ApplicationInput = {
        job_url: v.job_url.trim(),
        job_title: v.job_title.trim(),
        company: v.company.trim(),
        location: v.location.trim(),
        status: v.status,
        notes: v.notes,
      };
      if (v.applied_on) body.submitted_at = fromDateInput(v.applied_on);
      let saved = isEdit
        ? await applicationsApi.update(application.id, body)
        : await applicationsApi.create(body);
      if (resumeFile) saved = await applicationsApi.uploadResume(saved.id, resumeFile);
      onSaved(saved);
      onClose();
      notifications.show({ message: isEdit ? "Application updated." : "Application added.", color: "teal" });
    } catch (e) {
      notifications.show({ title: "Couldn't save", message: (e as Error).message, color: "red" });
    } finally {
      setSaving(false);
    }
  });

  return (
    <Modal opened={opened} onClose={onClose} title={isEdit ? "Edit application" : "Add application"} size="lg">
      <form onSubmit={submit}>
        <Stack gap="sm">
          <TextInput label="Job URL" placeholder="https://…" required {...form.getInputProps("job_url")} />
          <Group grow>
            <TextInput label="Job title" {...form.getInputProps("job_title")} />
            <TextInput label="Company" {...form.getInputProps("company")} />
          </Group>
          <Group grow>
            <TextInput label="Location" {...form.getInputProps("location")} />
            <Select
              label="Status"
              data={APPLICATION_STATUSES.map((s) => ({ value: s, label: s }))}
              allowDeselect={false}
              styles={{ input: { textTransform: "capitalize" } }}
              {...form.getInputProps("status")}
            />
            <TextInput type="date" label="Applied on" {...form.getInputProps("applied_on")} />
          </Group>
          <Textarea label="Notes" autosize minRows={2} maxRows={6} {...form.getInputProps("notes")} />
          <FileInput
            label={isEdit && application.applied_resume ? "Replace applied resume" : "Applied resume"}
            description={
              isEdit && application.applied_resume
                ? `Current: ${application.applied_resume.filename}`
                : "The resume you sent with this application (stored with it, max 5 MB)."
            }
            placeholder="Choose a .pdf or .docx"
            accept=".pdf,.doc,.docx,.rtf,.odt,.txt"
            leftSection={<IconFileText size={16} />}
            clearable
            value={resumeFile}
            onChange={setResumeFile}
          />
          {!isEdit && (
            <Text size="xs" c="dimmed">
              Applications you submit with the JobBot extension are added automatically once the site confirms them.
            </Text>
          )}
          <Group justify="flex-end" mt="xs">
            <Button variant="default" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" loading={saving}>
              {isEdit ? "Save changes" : "Add application"}
            </Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}
