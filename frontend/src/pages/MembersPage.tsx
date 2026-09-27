import {
  ActionIcon,
  Alert,
  Anchor,
  Badge,
  Box,
  Button,
  Container,
  Group,
  List,
  Modal,
  Paper,
  Select,
  Stack,
  Switch,
  Table,
  Text,
  TextInput,
  Title,
  Tooltip,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconAlertTriangle, IconRefresh, IconTrash, IconUsers } from "@tabler/icons-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { adminApi, type User } from "../auth/api";

type TemplateOption = { key: string; label: string };

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(new Date(iso));
  } catch {
    return iso;
  }
}

export default function MembersPage() {
  const [members, setMembers] = useState<User[]>([]);
  const [templateOptions, setTemplateOptions] = useState<TemplateOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [updatingId, setUpdatingId] = useState<string | null>(null);
  const [removing, setRemoving] = useState<User | null>(null);
  const [confirmText, setConfirmText] = useState("");
  const [removeBusy, setRemoveBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [memberData, templates] = await Promise.all([adminApi.listMembers(), adminApi.listTemplates()]);
      setMembers(memberData);
      setTemplateOptions(templates.map((t) => ({ key: t.key, label: t.label })));
    } catch (e) {
      notifications.show({
        title: "Could not load members",
        message: e instanceof Error ? e.message : "Try again.",
        color: "red",
      });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const selectData = useMemo(
    () => [{ value: "", label: "No template" }, ...templateOptions.map((t) => ({ value: t.key, label: t.label }))],
    [templateOptions],
  );

  const toggleAccess = async (member: User, hasAccess: boolean) => {
    if (member.role === "owner") return;
    setUpdatingId(member.id);
    try {
      const updated = await adminApi.setMemberAccess(member.id, hasAccess);
      setMembers((prev) => prev.map((m) => (m.id === updated.id ? updated : m)));
      notifications.show({
        title: hasAccess ? "Access granted" : "Access revoked",
        message: `${member.email} can ${hasAccess ? "now" : "no longer"} use the resume builder.`,
        color: "teal",
      });
    } catch (e) {
      notifications.show({
        title: "Update failed",
        message: e instanceof Error ? e.message : "Try again.",
        color: "red",
      });
    } finally {
      setUpdatingId(null);
    }
  };

  const togglePermission = async (member: User, allowed: boolean) => {
    if (member.role === "owner") return;
    setUpdatingId(member.id);
    try {
      const updated = await adminApi.setMemberPermissions(member.id, allowed);
      setMembers((prev) => prev.map((m) => (m.id === updated.id ? updated : m)));
      notifications.show({
        title: allowed ? "Team tracker access granted" : "Team tracker access removed",
        message: allowed
          ? `${member.email} can now see, add, edit and delete every member's tracked applications.`
          : `${member.email} can only see their own applications again.`,
        color: "teal",
      });
    } catch (e) {
      notifications.show({
        title: "Update failed",
        message: e instanceof Error ? e.message : "Try again.",
        color: "red",
      });
    } finally {
      setUpdatingId(null);
    }
  };

  const openRemove = (member: User) => {
    setConfirmText("");
    setRemoving(member);
  };

  const confirmRemove = async () => {
    if (!removing) return;
    setRemoveBusy(true);
    try {
      const r = await adminApi.removeMember(removing.id);
      setMembers((prev) => prev.filter((m) => m.id !== removing.id));
      notifications.show({
        title: "Member removed",
        message: `${r.email} was removed with ${r.applications_deleted} tracked application${
          r.applications_deleted === 1 ? "" : "s"
        } and ${r.files_deleted} stored file${r.files_deleted === 1 ? "" : "s"}.`,
        color: "teal",
      });
      setRemoving(null);
    } catch (e) {
      notifications.show({
        title: "Could not remove member",
        message: e instanceof Error ? e.message : "Try again.",
        color: "red",
      });
    } finally {
      setRemoveBusy(false);
    }
  };

  const changeTemplate = async (member: User, templateKey: string | null) => {
    if (member.role === "owner") return;
    setUpdatingId(member.id);
    try {
      await adminApi.setMemberTemplate(member.id, templateKey);
      await load();
      notifications.show({
        title: "Template updated",
        message: templateKey
          ? `${member.email} is now assigned that CV template.`
          : `${member.email} no longer has a CV template assigned.`,
        color: "teal",
      });
    } catch (e) {
      notifications.show({
        title: "Template change failed",
        message: e instanceof Error ? e.message : "Try again.",
        color: "red",
      });
      await load();
    } finally {
      setUpdatingId(null);
    }
  };

  return (
    <Container size="xl" py={{ base: "md", sm: "xl" }} px={{ base: "sm", md: "md" }}>
      <Stack gap="lg">
        <Group justify="space-between" align="flex-end" wrap="wrap">
          <Stack gap={4}>
            <Group gap="xs">
              <IconUsers size={24} stroke={1.5} />
              <Title order={2}>Member management</Title>
            </Group>
            <Text c="dimmed" size="sm" maw={640}>
              Review new sign-ups, grant builder access, assign CV templates (40 smart exclusive designs), and choose
              who can manage the team's tracked applications. Remove members you no longer work with.
            </Text>
          </Stack>
          <Button variant="light" color="teal" leftSection={<IconRefresh size={16} />} onClick={load} loading={loading}>
            Refresh
          </Button>
        </Group>

        <Paper withBorder radius="lg" bg="dark.7" style={{ overflow: "hidden" }}>
          <Box style={{ overflowX: "auto" }}>
            <Table striped highlightOnHover withTableBorder={false}>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Member</Table.Th>
                  <Table.Th>Status</Table.Th>
                  <Table.Th>CV template</Table.Th>
                  <Table.Th>Joined</Table.Th>
                  <Table.Th>Builder access</Table.Th>
                  <Table.Th>Team tracker</Table.Th>
                  <Table.Th>Applications</Table.Th>
                  <Table.Th w={48} />
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {members.map((member) => (
                  <Table.Tr key={member.id}>
                    <Table.Td>
                      <Stack gap={2}>
                        <Text fw={600} size="sm">
                          {member.name || "—"}
                        </Text>
                        <Text size="xs" c="dimmed">
                          {member.email}
                        </Text>
                      </Stack>
                    </Table.Td>
                    <Table.Td>
                      <Group gap={6}>
                        {member.role === "owner" ? (
                          <Badge color="grape" variant="light">
                            Owner
                          </Badge>
                        ) : null}
                        <Badge color={member.email_verified ? "teal" : "gray"} variant="outline" size="sm">
                          {member.email_verified ? "Verified" : "Unverified"}
                        </Badge>
                        <Badge color={member.has_access ? "teal" : "yellow"} variant="outline" size="sm">
                          {member.has_access ? "Approved" : "Pending"}
                        </Badge>
                        {member.has_access && member.role !== "owner" ? (
                          <Badge color="cyan" variant="light" size="sm">
                            Builder
                          </Badge>
                        ) : null}
                      </Group>
                    </Table.Td>
                    <Table.Td miw={200}>
                      {member.role === "owner" ? (
                        <Text size="sm" c="dimmed">
                          {member.cv_template_label || "—"}
                        </Text>
                      ) : (
                        <Select
                          size="xs"
                          data={selectData}
                          value={member.cv_template_key || ""}
                          disabled={updatingId === member.id}
                          placeholder="Assign template"
                          searchable
                          onChange={(value) =>
                            void changeTemplate(member, value && value.length > 0 ? value : null)
                          }
                        />
                      )}
                    </Table.Td>
                    <Table.Td>
                      <Text size="sm" c="dimmed">
                        {formatDate(member.created_at)}
                      </Text>
                    </Table.Td>
                    <Table.Td>
                      {member.role === "owner" ? (
                        <Text size="sm" c="dimmed">
                          Always on
                        </Text>
                      ) : (
                        <Switch
                          checked={member.has_access}
                          disabled={!member.email_verified || updatingId === member.id}
                          onChange={(e) => void toggleAccess(member, e.currentTarget.checked)}
                          color="teal"
                          label={member.has_access ? "Granted" : "No access"}
                          size="sm"
                        />
                      )}
                    </Table.Td>
                    <Table.Td>
                      {member.role === "owner" ? (
                        <Text size="sm" c="dimmed">
                          Always on
                        </Text>
                      ) : (
                        <Tooltip
                          label={
                            member.has_access
                              ? "Lets this member see, add, edit and delete every member's tracked applications"
                              : "Grant builder access first"
                          }
                          withArrow
                          multiline
                          w={240}
                        >
                          <div>
                            <Switch
                              checked={member.can_manage_applications}
                              disabled={!member.has_access || updatingId === member.id}
                              onChange={(e) => void togglePermission(member, e.currentTarget.checked)}
                              color="grape"
                              label={member.can_manage_applications ? "Can manage" : "Own only"}
                              size="sm"
                            />
                          </div>
                        </Tooltip>
                      )}
                    </Table.Td>
                    <Table.Td>
                      <Anchor component={Link} to={`/admin/applications?member=${member.id}`} size="sm">
                        View tracker
                      </Anchor>
                    </Table.Td>
                    <Table.Td>
                      {member.role === "owner" ? null : (
                        <Tooltip label="Remove member" withArrow>
                          <ActionIcon
                            variant="subtle"
                            color="red"
                            aria-label={`Remove ${member.email}`}
                            disabled={updatingId === member.id}
                            onClick={() => openRemove(member)}
                          >
                            <IconTrash size={16} />
                          </ActionIcon>
                        </Tooltip>
                      )}
                    </Table.Td>
                  </Table.Tr>
                ))}
                {!loading && members.length === 0 ? (
                  <Table.Tr>
                    <Table.Td colSpan={8}>
                      <Text ta="center" c="dimmed" py="md">
                        No members yet.
                      </Text>
                    </Table.Td>
                  </Table.Tr>
                ) : null}
              </Table.Tbody>
            </Table>
          </Box>
        </Paper>
      </Stack>

      <Modal
        opened={removing != null}
        onClose={() => !removeBusy && setRemoving(null)}
        title="Remove member?"
        size="md"
      >
        <Stack gap="md">
          <Alert color="red" variant="light" icon={<IconAlertTriangle size={18} />}>
            This permanently deletes <b>{removing?.name || removing?.email}</b> and cannot be undone.
          </Alert>
          <List size="sm" spacing={4}>
            <List.Item>Their account, profile, saved base resume and autofill profile</List.Item>
            <List.Item>All their tracked job applications and applied resumes</List.Item>
            <List.Item>Their generated tailored resumes</List.Item>
            <List.Item>Their CV template assignment (the template becomes free again)</List.Item>
          </List>
          <Text size="sm" c="dimmed">
            They're signed out everywhere immediately. They could sign up again later as a new member.
          </Text>
          <TextInput
            label={
              <>
                Type <b>{removing?.email}</b> to confirm
              </>
            }
            value={confirmText}
            onChange={(e) => setConfirmText(e.currentTarget.value)}
            autoComplete="off"
            data-autofocus
          />
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setRemoving(null)} disabled={removeBusy}>
              Cancel
            </Button>
            <Button
              color="red"
              leftSection={<IconTrash size={16} />}
              loading={removeBusy}
              disabled={confirmText.trim().toLowerCase() !== (removing?.email || "").toLowerCase()}
              onClick={confirmRemove}
            >
              Remove member
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Container>
  );
}
