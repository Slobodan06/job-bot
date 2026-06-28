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
import { notifications } from "@mantine/notifications";
import { IconMail } from "@tabler/icons-react";
import { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";

import { authApi } from "../auth/api";

export default function CheckEmailPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const emailFromState = (location.state as { email?: string } | null)?.email;
  const params = new URLSearchParams(location.search);
  const email = emailFromState || params.get("email") || "";
  const [sending, setSending] = useState(false);

  const resend = async () => {
    if (!email) {
      notifications.show({ title: "Missing email", message: "Sign up again to receive a new link.", color: "red" });
      return;
    }
    setSending(true);
    try {
      const res = await authApi.resendVerification(email);
      notifications.show({ title: "Email sent", message: res.message, color: "teal" });
    } catch (e) {
      notifications.show({
        title: "Could not resend",
        message: e instanceof Error ? e.message : "Try again.",
        color: "red",
      });
    } finally {
      setSending(false);
    }
  };

  return (
    <Box py={{ base: "xl", md: "calc(4 * var(--mantine-spacing-xl))" }} px="md">
      <Paper maw={520} mx="auto" p={{ base: "lg", sm: "xl" }} radius="lg" withBorder shadow="md" bg="dark.7">
        <Stack gap="lg" align="center" ta="center">
          <IconMail size={48} stroke={1.25} color="var(--mantine-color-teal-5)" />
          <Stack gap={4}>
            <Title order={2} fz={rem(26)}>
              Check your email
            </Title>
            <Text c="dimmed" size="sm">
              We sent an activation link from{" "}
              <Text span fw={600} c="teal">
                Vukasin@nivion.tech
              </Text>
              {email ? (
                <>
                  {" "}
                  to <Text span fw={600}>{email}</Text>
                </>
              ) : null}
              . Click the link to verify your account and continue.
            </Text>
          </Stack>
          <Alert variant="light" color="teal" w="100%">
            After you verify your email, the manager may still need to approve builder access.
          </Alert>
          <Stack gap="sm" w="100%">
            <Button color="teal" variant="light" fullWidth loading={sending} onClick={() => void resend()}>
              Resend activation email
            </Button>
            <Button component={Link} to="/auth" variant="default" fullWidth>
              Back to sign in
            </Button>
            <Button variant="subtle" fullWidth onClick={() => navigate("/auth", { replace: true })}>
              Use a different email
            </Button>
          </Stack>
        </Stack>
      </Paper>
    </Box>
  );
}
