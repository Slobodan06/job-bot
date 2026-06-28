import {
  Alert,
  Box,
  Button,
  Paper,
  PasswordInput,
  Stack,
  Tabs,
  Text,
  TextInput,
  Title,
  rem,
} from "@mantine/core";
import { useForm } from "@mantine/form";
import { notifications } from "@mantine/notifications";
import { IconAlertCircle, IconLock, IconMail, IconUser } from "@tabler/icons-react";
import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { getPostAuthPath, useAuth } from "../auth/AuthContext";

export default function AuthPage() {
  const [params] = useSearchParams();
  const initialTab = params.get("mode") === "signup" ? "signup" : "signin";
  const [tab, setTab] = useState<string | null>(initialTab);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { login, register } = useAuth();
  const navigate = useNavigate();

  const signInForm = useForm({
    initialValues: { email: "", password: "" },
    validate: {
      email: (v: string) => (/^\S+@\S+$/.test(v) ? null : "Enter a valid email"),
      password: (v: string) => (v.length >= 1 ? null : "Password is required"),
    },
  });

  const signUpForm = useForm({
    initialValues: { name: "", email: "", password: "", confirm: "" },
    validate: {
      name: (v: string) => (v.trim().length >= 1 ? null : "Name is required"),
      email: (v: string) => (/^\S+@\S+$/.test(v) ? null : "Enter a valid email"),
      password: (v: string) => (v.length >= 8 ? null : "At least 8 characters"),
      confirm: (v: string, values: { password: string }) =>
        v === values.password ? null : "Passwords do not match",
    },
  });

  const handleResult = (res: Awaited<ReturnType<typeof login>>) => {
    if (res.status === "pending_access") {
      notifications.show({ title: "Account created", message: res.message, color: "yellow" });
      navigate("/pending-access", { replace: true });
      return;
    }
    notifications.show({ title: "Welcome", message: res.message, color: "teal" });
    navigate(getPostAuthPath(res.user ?? null, res.status), { replace: true });
  };

  const onSignIn = signInForm.onSubmit(async (values) => {
    setError(null);
    setSubmitting(true);
    try {
      const res = await login(values.email, values.password);
      handleResult(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Sign in failed.");
    } finally {
      setSubmitting(false);
    }
  });

  const onSignUp = signUpForm.onSubmit(async (values) => {
    setError(null);
    setSubmitting(true);
    try {
      const res = await register(values.email, values.password, values.name.trim());
      handleResult(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Sign up failed.");
    } finally {
      setSubmitting(false);
    }
  });

  return (
    <Box py={{ base: "xl", md: "calc(4 * var(--mantine-spacing-xl))" }} px="md">
      <Paper
        maw={480}
        mx="auto"
        p={{ base: "lg", sm: "xl" }}
        radius="lg"
        withBorder
        shadow="md"
        bg="dark.7"
      >
        <Stack gap="lg">
          <Stack gap={4} ta="center">
            <Title order={2} fz={rem(28)}>
              {tab === "signup" ? "Create your account" : "Welcome back"}
            </Title>
            <Text c="dimmed" size="sm">
              {tab === "signup"
                ? "Sign up with email. A manager must approve your account before you can use the builder."
                : "Sign in with your email and password."}
            </Text>
          </Stack>

          {error ? (
            <Alert icon={<IconAlertCircle size={18} />} color="red" variant="light">
              {error}
            </Alert>
          ) : null}

          <Tabs value={tab} onChange={setTab} variant="pills" radius="md" color="teal">
            <Tabs.List grow mb="md">
              <Tabs.Tab value="signin">Sign in</Tabs.Tab>
              <Tabs.Tab value="signup">Sign up</Tabs.Tab>
            </Tabs.List>

            <Tabs.Panel value="signin">
              <form onSubmit={onSignIn}>
                <Stack gap="md">
                  <TextInput
                    label="Email"
                    placeholder="you@example.com"
                    leftSection={<IconMail size={16} />}
                    {...signInForm.getInputProps("email")}
                  />
                  <PasswordInput
                    label="Password"
                    placeholder="Your password"
                    leftSection={<IconLock size={16} />}
                    {...signInForm.getInputProps("password")}
                  />
                  <Button type="submit" color="teal" fullWidth loading={submitting}>
                    Sign in
                  </Button>
                </Stack>
              </form>
            </Tabs.Panel>

            <Tabs.Panel value="signup">
              <form onSubmit={onSignUp}>
                <Stack gap="md">
                  <TextInput
                    label="Full name"
                    placeholder="Jane Doe"
                    leftSection={<IconUser size={16} />}
                    {...signUpForm.getInputProps("name")}
                  />
                  <TextInput
                    label="Email"
                    placeholder="you@example.com"
                    leftSection={<IconMail size={16} />}
                    {...signUpForm.getInputProps("email")}
                  />
                  <PasswordInput
                    label="Password"
                    placeholder="At least 8 characters"
                    leftSection={<IconLock size={16} />}
                    {...signUpForm.getInputProps("password")}
                  />
                  <PasswordInput
                    label="Confirm password"
                    placeholder="Repeat password"
                    leftSection={<IconLock size={16} />}
                    {...signUpForm.getInputProps("confirm")}
                  />
                  <Button type="submit" color="teal" fullWidth loading={submitting}>
                    Create account
                  </Button>
                </Stack>
              </form>
            </Tabs.Panel>
          </Tabs>

          <Text ta="center" size="xs" c="dimmed">
            After sign up, the site owner reviews new accounts and grants builder access.
          </Text>
        </Stack>
      </Paper>
    </Box>
  );
}
