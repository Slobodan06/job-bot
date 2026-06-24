import {
  Badge,
  Box,
  Button,
  Container,
  Group,
  Paper,
  Select,
  Stack,
  Switch,
  Table,
  Text,
  Title,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconRefresh, IconUsers } from "@tabler/icons-react";
import { useCallback, useEffect, useMemo, useState } from "react";

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
              Grant builder access, assign CV templates (40 smart exclusive designs), or change a member&apos;s template.
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
                  </Table.Tr>
                ))}
                {!loading && members.length === 0 ? (
                  <Table.Tr>
                    <Table.Td colSpan={5}>
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
    </Container>
  );
}
