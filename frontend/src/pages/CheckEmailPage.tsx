import {
  Alert,
  Anchor,
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
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";

import { authApi } from "../auth/api";

export default function CheckEmailPage() {
  const location = useLocation();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const email =
    params.get("email") ??
    (location.state as { email?: string } | null)?.email ??
    "";
  const [sending, setSending] = useState(false);

  const resend = async () => {
    if (!email) {
      navigate("/auth");
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
              We sent an activation link to{" "}
              <Text component="span" fw={600} c="gray.1">
                {email || "your email"}
              </Text>
              . Click the link to verify your account and continue.
            </Text>
          </Stack>
          <Alert variant="light" color="teal" w="100%">
            After activation, the site owner may need to grant you access to the resume builder.
          </Alert>
          <Stack gap="sm" w="100%">
            <Button color="teal" variant="light" fullWidth loading={sending} onClick={resend} disabled={!email}>
              Resend activation email
            </Button>
            <Button component={Link} to="/auth" variant="default" fullWidth>
              Back to sign in
            </Button>
          </Stack>
          <Text size="xs" c="dimmed">
            Did not receive it? Check spam or{" "}
            <Anchor component="button" type="button" onClick={resend} size="xs">
              resend the link
            </Anchor>
            .
          </Text>
        </Stack>
      </Paper>
    </Box>
  );
}
