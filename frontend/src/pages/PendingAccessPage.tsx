import {
  Alert,
  Box,
  Button,
  Paper,
  Stack,
  Text,
  Title,
  rem,
} from "@mantine/core";
import { IconClockHour4 } from "@tabler/icons-react";
import { Link, useNavigate } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";

export default function PendingAccessPage() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  return (
    <Box py={{ base: "xl", md: "calc(4 * var(--mantine-spacing-xl))" }} px="md">
      <Paper maw={520} mx="auto" p={{ base: "lg", sm: "xl" }} radius="lg" withBorder shadow="md" bg="dark.7">
        <Stack gap="lg" align="center" ta="center">
          <IconClockHour4 size={48} stroke={1.25} color="var(--mantine-color-yellow-5)" />
          <Stack gap={4}>
            <Title order={2} fz={rem(26)}>
              Access pending
            </Title>
            <Text c="dimmed" size="sm">
              Hi {user?.name || user?.email}, your email is verified but the manager has not granted
              resume builder access yet.
            </Text>
          </Stack>
          <Alert variant="light" color="yellow" w="100%">
            Once approved, you will be able to upload resumes and generate tailored results. You can still
            update your profile in the meantime.
          </Alert>
          <Stack gap="sm" w="100%">
            <Button component={Link} to="/profile" color="teal" variant="light" fullWidth>
              View profile
            </Button>
            <Button variant="default" fullWidth onClick={() => { logout(); navigate("/auth"); }}>
              Sign out
            </Button>
          </Stack>
        </Stack>
      </Paper>
    </Box>
  );
}
