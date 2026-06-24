import {
  Avatar,
  Badge,
  Box,
  Button,
  Container,
  Group,
  Loader,
  Menu,
  rem,
  Stack,
  Text,
  Title,
  UnstyledButton,
} from "@mantine/core";
import { IconChevronDown, IconFileCv, IconLayoutGrid, IconLogout, IconUser, IconUsers } from "@tabler/icons-react";
import { Link, Outlet, useLocation, useNavigate } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";

function userInitials(name: string, email: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length >= 2) return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return email.slice(0, 2).toUpperCase();
}

function pageTitle(pathname: string): string {
  if (pathname.startsWith("/builder")) return "Resume builder";
  if (pathname.startsWith("/templates")) return "CV templates";
  if (pathname.startsWith("/profile")) return "Your profile";
  if (pathname.startsWith("/admin/members")) return "Member management";
  if (pathname.startsWith("/auth")) return "Account";
  if (pathname.startsWith("/pending-access")) return "Access pending";
  return "Resume tailor";
}

export function AppLayout() {
  const { user, loading, logout, isAuthenticated, canBuild, isOwner } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const isBuilder = location.pathname.startsWith("/builder");
  const isAuthLanding = location.pathname === "/auth";

  return (
    <Box component="main" mih="100dvh" bg="dark.8">
      <Box
        component="header"
        py={{ base: "sm", md: "md" }}
        px={{ base: "md", md: "lg" }}
        style={{
          borderBottom: "1px solid var(--mantine-color-dark-4)",
          position: "sticky",
          top: 0,
          zIndex: 100,
          backdropFilter: "blur(12px)",
          background: "rgba(26, 27, 30, 0.85)",
        }}
      >
        <Container size="xl">
          <Group justify="space-between" align="flex-start" wrap="nowrap" gap="md">
            <Stack gap={4} miw={0} style={{ flex: 1 }}>
              <Group gap="xs" wrap="wrap">
                <Badge
                  component={Link}
                  to={isAuthenticated && canBuild ? "/builder" : "/auth"}
                  variant="dot"
                  color="teal"
                  size="lg"
                  radius="sm"
                  style={{ cursor: "pointer", textDecoration: "none" }}
                >
                  Resume tailor
                </Badge>
                {isOwner ? (
                  <Badge variant="light" color="grape" size="sm">
                    Owner
                  </Badge>
                ) : null}
              </Group>
              {isBuilder ? (
                <>
                  <Title order={1} fz={{ base: rem(26), sm: rem(34), md: rem(38) }} lh={1.2}>
                    Resume builder
                  </Title>
                  <Text maw={720} c="dimmed" size="sm" visibleFrom="xs">
                    Upload a resume, paste the job posting, and get tailored profile, experience, and skills you can copy.
                  </Text>
                </>
              ) : (
                <Title order={2} fz={{ base: rem(22), sm: rem(28) }} lh={1.2}>
                  {pageTitle(location.pathname)}
                </Title>
              )}
            </Stack>

            <Group gap="sm" wrap="nowrap" mt={{ base: 4, md: 8 }}>
              {loading ? (
                <Loader size="sm" color="teal" />
              ) : isAuthenticated && user ? (
                <Menu shadow="md" width={240} position="bottom-end" withinPortal>
                  <Menu.Target>
                    <UnstyledButton
                      style={{
                        padding: "6px 10px",
                        borderRadius: "var(--mantine-radius-md)",
                        border: "1px solid var(--mantine-color-dark-4)",
                      }}
                    >
                      <Group gap="xs" wrap="nowrap">
                        <Avatar src={user.avatar_url || undefined} radius="xl" size={32} color="teal">
                          {userInitials(user.name, user.email)}
                        </Avatar>
                        <Box visibleFrom="sm">
                          <Text size="sm" fw={600} lineClamp={1} maw={140}>
                            {user.name || user.email}
                          </Text>
                          <Text size="xs" c="dimmed" lineClamp={1} maw={140}>
                            {user.headline || user.email}
                          </Text>
                        </Box>
                        <IconChevronDown size={16} stroke={1.5} style={{ opacity: 0.6 }} />
                      </Group>
                    </UnstyledButton>
                  </Menu.Target>
                  <Menu.Dropdown>
                    <Menu.Label>Signed in as {user.email}</Menu.Label>
                    {canBuild ? (
                      <>
                        <Menu.Item leftSection={<IconFileCv size={16} />} component={Link} to="/builder">
                          Resume builder
                        </Menu.Item>
                        <Menu.Item leftSection={<IconLayoutGrid size={16} />} component={Link} to="/templates">
                          CV template{user.cv_template_label ? `: ${user.cv_template_label}` : "s"}
                        </Menu.Item>
                      </>
                    ) : null}
                    <Menu.Item leftSection={<IconUser size={16} />} component={Link} to="/profile">
                      Profile settings
                    </Menu.Item>
                    {isOwner ? (
                      <Menu.Item leftSection={<IconUsers size={16} />} component={Link} to="/admin/members">
                        Manage members
                      </Menu.Item>
                    ) : null}
                    <Menu.Divider />
                    <Menu.Item
                      color="red"
                      leftSection={<IconLogout size={16} />}
                      onClick={() => {
                        logout();
                        navigate("/auth");
                      }}
                    >
                      Sign out
                    </Menu.Item>
                  </Menu.Dropdown>
                </Menu>
              ) : isAuthLanding ? null : (
                <Group gap="xs" wrap="nowrap">
                  <Button variant="default" component={Link} to="/auth" size="sm">
                    Sign in
                  </Button>
                  <Button component={Link} to="/auth?mode=signup" color="teal" size="sm">
                    Get started
                  </Button>
                </Group>
              )}
            </Group>
          </Group>
        </Container>
      </Box>

      <Outlet />
    </Box>
  );
}
