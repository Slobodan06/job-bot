import { Alert, Box, Button, Center, Loader, Paper, Stack, Text, Title, rem } from "@mantine/core";
import { IconAlertCircle, IconCheck } from "@tabler/icons-react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { getPostAuthPath, useAuth } from "../auth/AuthContext";
import type { AuthResult } from "../auth/api";

export default function VerifyEmailPage() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const { verifyEmail } = useAuth();
  const navigate = useNavigate();
  const [status, setStatus] = useState<"loading" | "success" | "error">("loading");
  const [message, setMessage] = useState("");
  const [result, setResult] = useState<AuthResult | null>(null);

  useEffect(() => {
    if (!token) {
      setStatus("error");
      setMessage("Missing activation token.");
      return;
    }
    void (async () => {
      try {
        const res = await verifyEmail(token);
        setResult(res);
        setMessage(res.message);
        setStatus("success");
        setTimeout(() => {
          navigate(getPostAuthPath(res.user ?? null, res.status), { replace: true });
        }, 1800);
      } catch (e) {
        setStatus("error");
        setMessage(e instanceof Error ? e.message : "Activation failed.");
      }
    })();
  }, [token, verifyEmail, navigate]);

  return (
    <Box py={{ base: "xl", md: "calc(4 * var(--mantine-spacing-xl))" }} px="md">
      <Paper maw={480} mx="auto" p={{ base: "lg", sm: "xl" }} radius="lg" withBorder shadow="md" bg="dark.7">
        {status === "loading" ? (
          <Center py="xl">
            <Stack align="center" gap="md">
              <Loader color="teal" />
              <Text c="dimmed" size="sm">
                Activating your account…
              </Text>
            </Stack>
          </Center>
        ) : status === "success" ? (
          <Stack gap="md" align="center" ta="center">
            <IconCheck size={48} color="var(--mantine-color-teal-5)" />
            <Title order={2} fz={rem(24)}>
              Account activated
            </Title>
            <Text c="dimmed" size="sm">
              {message}
            </Text>
            {result?.status === "pending_access" ? (
              <Alert color="yellow" variant="light" w="100%">
                Your email is verified. Waiting for the owner to grant resume builder access.
              </Alert>
            ) : (
              <Text size="sm" c="dimmed">
                Redirecting…
              </Text>
            )}
            <Button
              component={Link}
              to={getPostAuthPath(result?.user ?? null, result?.status)}
              color="teal"
            >
              Continue
            </Button>
          </Stack>
        ) : (
          <Stack gap="md" align="center" ta="center">
            <IconAlertCircle size={48} color="var(--mantine-color-red-5)" />
            <Title order={2} fz={rem(24)}>
              Activation failed
            </Title>
            <Alert color="red" variant="light" w="100%">
              {message}
            </Alert>
            <Button component={Link} to="/auth" color="teal">
              Back to sign in
            </Button>
          </Stack>
        )}
      </Paper>
    </Box>
  );
}
