import {
  Avatar,
  Badge,
  Button,
  Container,
  Divider,
  Grid,
  Group,
  Paper,
  PasswordInput,
  rem,
  Stack,
  Text,
  TextInput,
  Textarea,
  Title,
} from "@mantine/core";
import { useForm } from "@mantine/form";
import { notifications } from "@mantine/notifications";
import {
  IconBriefcase,
  IconLock,
  IconMapPin,
  IconQuote,
  IconUser,
} from "@tabler/icons-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { authApi } from "../auth/api";
import { useAuth } from "../auth/AuthContext";

function userInitials(name: string, email: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length >= 2) return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return email.slice(0, 2).toUpperCase();
}

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(new Date(iso));
  } catch {
    return iso;
  }
}

export default function ProfilePage() {
  const { user, refreshUser, logout } = useAuth();
  const navigate = useNavigate();
  const [savingProfile, setSavingProfile] = useState(false);
  const [savingPassword, setSavingPassword] = useState(false);

  const profileForm = useForm({
    initialValues: {
      name: "",
      headline: "",
      target_role: "",
      location: "",
      bio: "",
    },
    validate: {
      name: (v: string) => (v.trim().length >= 1 ? null : "Name is required"),
    },
  });

  const passwordForm = useForm({
    initialValues: {
      current_password: "",
      new_password: "",
      confirm: "",
    },
    validate: {
      current_password: (v: string) => (v.length >= 1 ? null : "Required"),
      new_password: (v: string) => (v.length >= 8 ? null : "At least 8 characters"),
      confirm: (v: string, values: { new_password: string }) =>
        v === values.new_password ? null : "Passwords do not match",
    },
  });

  useEffect(() => {
    if (!user) return;
    profileForm.setValues({
      name: user.name,
      headline: user.headline,
      target_role: user.target_role,
      location: user.location,
      bio: user.bio,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.id]);

  if (!user) return null;

  const onSaveProfile = profileForm.onSubmit(async (values) => {
    setSavingProfile(true);
    try {
      await authApi.updateProfile({
        name: values.name.trim(),
        headline: values.headline.trim(),
        target_role: values.target_role.trim(),
        location: values.location.trim(),
        bio: values.bio.trim(),
      });
      await refreshUser();
      notifications.show({ title: "Profile saved", message: "Your changes were updated.", color: "teal" });
    } catch (e) {
      notifications.show({
        title: "Could not save",
        message: e instanceof Error ? e.message : "Try again.",
        color: "red",
      });
    } finally {
      setSavingProfile(false);
    }
  });

  const onChangePassword = passwordForm.onSubmit(async (values) => {
    setSavingPassword(true);
    try {
      await authApi.changePassword(values.current_password, values.new_password);
      passwordForm.reset();
      notifications.show({ title: "Password updated", message: "Use your new password next time.", color: "teal" });
    } catch (e) {
      notifications.show({
        title: "Password change failed",
        message: e instanceof Error ? e.message : "Try again.",
        color: "red",
      });
    } finally {
      setSavingPassword(false);
    }
  });

  return (
    <Container size="lg" py={{ base: "md", sm: "xl" }} px={{ base: "sm", md: "md" }}>
      <Grid gutter={{ base: "md", md: "xl" }}>
        <Grid.Col span={{ base: 12, md: 4 }}>
          <Paper withBorder radius="lg" p="lg" bg="dark.7" style={{ position: "sticky", top: rem(88) }}>
            <Stack align="center" gap="md">
              <Avatar src={user.avatar_url || undefined} size={96} radius={96} color="teal">
                {userInitials(user.name, user.email)}
              </Avatar>
              <Stack gap={4} align="center" w="100%">
                <Title order={3} ta="center" lineClamp={2}>
                  {user.name || "Unnamed"}
                </Title>
                {user.headline ? (
                  <Text c="dimmed" size="sm" ta="center" lineClamp={2}>
                    {user.headline}
                  </Text>
                ) : null}
                <Badge variant="light" color={user.role === "owner" ? "grape" : "teal"}>
                  {user.role === "owner" ? "Owner" : "Member"}
                </Badge>
                <Badge variant="outline" color={user.email_verified ? "teal" : "gray"}>
                  {user.email_verified ? "Verified" : "Unverified"}
                </Badge>
                {user.has_access || user.role === "owner" ? (
                  <Badge variant="light" color="cyan">
                    Builder access
                  </Badge>
                ) : (
                  <Badge variant="light" color="yellow">
                    Access pending
                  </Badge>
                )}
                {user.cv_template_label ? (
                  <Badge variant="outline" color="grape">
                    CV: {user.cv_template_label}
                  </Badge>
                ) : null}
              </Stack>
              <Divider w="100%" />
              <Stack gap="xs" w="100%">
                <Group justify="space-between">
                  <Text size="xs" c="dimmed">
                    Email
                  </Text>
                  <Text size="xs" fw={500} ta="right" maw="60%" truncate>
                    {user.email}
                  </Text>
                </Group>
                <Group justify="space-between">
                  <Text size="xs" c="dimmed">
                    Member since
                  </Text>
                  <Text size="xs" fw={500}>
                    {formatDate(user.created_at)}
                  </Text>
                </Group>
                {user.target_role ? (
                  <Group justify="space-between" align="flex-start">
                    <Text size="xs" c="dimmed">
                      Target role
                    </Text>
                    <Text size="xs" fw={500} ta="right" maw="60%">
                      {user.target_role}
                    </Text>
                  </Group>
                ) : null}
              </Stack>
              <Button
                variant="light"
                color="red"
                fullWidth
                onClick={() => {
                  logout();
                  navigate("/auth");
                }}
              >
                Sign out
              </Button>
            </Stack>
          </Paper>
        </Grid.Col>

        <Grid.Col span={{ base: 12, md: 8 }}>
          <Stack gap="lg">
            <Paper withBorder radius="lg" p={{ base: "md", sm: "lg" }} bg="dark.7">
              <Stack gap="md">
                <div>
                  <Title order={3} size="h4">
                    Career profile
                  </Title>
                  <Text size="sm" c="dimmed">
                    These details help personalize your resume tailoring experience.
                  </Text>
                </div>
                <form onSubmit={onSaveProfile}>
                  <Stack gap="md">
                    <TextInput
                      label="Display name"
                      leftSection={<IconUser size={16} />}
                      {...profileForm.getInputProps("name")}
                    />
                    <TextInput
                      label="Headline"
                      placeholder="e.g. Senior Frontend Engineer · React & TypeScript"
                      leftSection={<IconQuote size={16} />}
                      {...profileForm.getInputProps("headline")}
                    />
                    <TextInput
                      label="Target role"
                      placeholder="e.g. Full-stack Developer"
                      leftSection={<IconBriefcase size={16} />}
                      {...profileForm.getInputProps("target_role")}
                    />
                    <TextInput
                      label="Location"
                      placeholder="City, Country or Remote"
                      leftSection={<IconMapPin size={16} />}
                      {...profileForm.getInputProps("location")}
                    />
                    <Textarea
                      label="Bio"
                      placeholder="Short summary about your experience and goals…"
                      minRows={4}
                      autosize
                      {...profileForm.getInputProps("bio")}
                    />
                    <Group justify="flex-end">
                      <Button type="submit" color="teal" loading={savingProfile}>
                        Save profile
                      </Button>
                    </Group>
                  </Stack>
                </form>
              </Stack>
            </Paper>

            <Paper withBorder radius="lg" p={{ base: "md", sm: "lg" }} bg="dark.7">
              <Stack gap="md">
                <div>
                  <Title order={3} size="h4">
                    Security
                  </Title>
                  <Text size="sm" c="dimmed">
                    Update your password for email sign-in.
                  </Text>
                </div>
                <form onSubmit={onChangePassword}>
                  <Stack gap="md">
                    <PasswordInput
                      label="Current password"
                      leftSection={<IconLock size={16} />}
                      {...passwordForm.getInputProps("current_password")}
                    />
                    <PasswordInput
                      label="New password"
                      leftSection={<IconLock size={16} />}
                      {...passwordForm.getInputProps("new_password")}
                    />
                    <PasswordInput
                      label="Confirm new password"
                      leftSection={<IconLock size={16} />}
                      {...passwordForm.getInputProps("confirm")}
                    />
                    <Group justify="flex-end">
                      <Button type="submit" variant="light" color="teal" loading={savingPassword}>
                        Update password
                      </Button>
                    </Group>
                  </Stack>
                </form>
              </Stack>
            </Paper>
          </Stack>
        </Grid.Col>
      </Grid>
    </Container>
  );
}
