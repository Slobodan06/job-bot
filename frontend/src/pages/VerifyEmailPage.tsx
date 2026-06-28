import { Alert, Box, Button, Center, Loader, Paper, Stack, Text, Title, rem } from "@mantine/core";
import { IconAlertCircle, IconCircleCheck } from "@tabler/icons-react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { getPostAuthPath, useAuth } from "../auth/AuthContext";
import type { AuthResult } from "../auth/api";

export default function VerifyEmailPage() {
  const [params] = useSearchParams();
  const token = params.get("token") || "";
  const { verifyEmail } = useAuth();
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<AuthResult | null>(null);

  useEffect(() => {
    if (!token) {
      setError("This activation link is missing or invalid.");
      setLoading(false);
      return;
    }
    void (async () => {
      try {
        const res = await verifyEmail(token);
        setResult(res);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Activation failed.");
      } finally {
        setLoading(false);
      }
    })();
  }, [token, verifyEmail]);

  if (loading) {
    return (
      <Center mih="50dvh">
        <Loader color="teal" />
      </Center>
    );
  }

  return (
    <Box py={{ base: "xl", md: "calc(4 * var(--mantine-spacing-xl))" }} px="md">
      <Paper maw={520} mx="auto" p={{ base: "lg", sm: "xl" }} radius="lg" withBorder shadow="md" bg="dark.7">
        <Stack gap="lg" align="center" ta="center">
          {error ? (
            <>
              <IconAlertCircle size={48} stroke={1.25} color="var(--mantine-color-red-5)" />
              <Title order={2} fz={rem(26)}>
                Activation failed
              </Title>
              <Alert variant="light" color="red" w="100%">
                {error}
              </Alert>
              <Button component={Link} to="/auth" color="teal" fullWidth>
                Back to sign in
              </Button>
            </>
          ) : (
            <>
              <IconCircleCheck size={48} stroke={1.25} color="var(--mantine-color-teal-5)" />
              <Title order={2} fz={rem(26)}>
                Email verified
              </Title>
              <Text c="dimmed" size="sm">
                {result?.message || "Your account is activated."}
              </Text>
              {result?.status === "pending_access" ? (
                <Alert variant="light" color="yellow" w="100%">
                  Your email is verified. Waiting for the manager to grant resume builder access.
                </Alert>
              ) : null}
              <Button
                color="teal"
                fullWidth
                onClick={() => navigate(getPostAuthPath(result?.user ?? null, result?.status ?? undefined), { replace: true })}
              >
                Continue
              </Button>
            </>
          )}
        </Stack>
      </Paper>
    </Box>
  );
}
