import {
  ActionIcon,
  Alert,
  Badge,
  Box,
  Button,
  Group,
  Paper,
  ScrollArea,
  SegmentedControl,
  Stack,
  Text,
  Textarea,
  ThemeIcon,
  Title,
  Tooltip,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import {
  IconAlertCircle,
  IconCheck,
  IconCopy,
  IconMessageQuestion,
  IconPlayerStopFilled,
  IconRefresh,
  IconSend,
  IconSparkles,
} from "@tabler/icons-react";
import { useEffect, useRef, useState } from "react";

import { applicationAnswerApi, type AnswerLength, type ChatTurn } from "../auth/api";

type Props = {
  file: File | null;
  jobDescription: string;
  companyName: string;
  height: Record<string, string>;
};

const EXAMPLES = [
  "Why do you want to work at this company?",
  "Why are you a good fit for this role?",
  "Tell us about a challenging project you led and its outcome.",
  "Describe your experience with the main technologies in this job.",
  "What are your salary expectations?",
];

const FOLLOW_UPS = ["Make it shorter", "Make it more specific to the job", "More technical detail"];

export function ApplicationQuestionsChat({ file, jobDescription, companyName, height }: Props) {
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [draft, setDraft] = useState("");
  const [length, setLength] = useState<AnswerLength>("standard");
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const viewportRef = useRef<HTMLDivElement>(null);

  // Keep the newest text in view while it streams in.
  useEffect(() => {
    const vp = viewportRef.current;
    if (vp) vp.scrollTo({ top: vp.scrollHeight });
  }, [turns]);

  useEffect(() => () => abortRef.current?.abort(), []);

  const ask = async (question: string) => {
    const q = question.trim();
    if (!q || streaming) return;
    const history = turns;
    setError(null);
    setDraft("");
    setTurns([...history, { role: "user", content: q }, { role: "assistant", content: "" }]);
    setStreaming(true);
    const controller = new AbortController();
    abortRef.current = controller;

    const setAnswer = (text: string) =>
      setTurns((prev) => {
        const next = [...prev];
        next[next.length - 1] = { role: "assistant", content: text };
        return next;
      });

    try {
      await applicationAnswerApi.stream(
        { question: q, resume: file, jobDescription, companyName, length, history },
        setAnswer,
        controller.signal,
      );
    } catch (e) {
      if (controller.signal.aborted) return; // user pressed Stop — keep the partial answer
      // Drop the failed exchange and put the question back so it can be retried.
      setTurns(history);
      setDraft(q);
      setError(e instanceof Error ? e.message : "Something went wrong.");
    } finally {
      setStreaming(false);
      abortRef.current = null;
    }
  };

  const copy = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      notifications.show({ title: "Copied", message: "Answer copied to clipboard.", color: "teal", icon: <IconCheck size={18} /> });
    } catch {
      notifications.show({ title: "Copy failed", message: "Your browser blocked clipboard access.", color: "orange" });
    }
  };

  const lastAnswer = turns.length && turns[turns.length - 1].role === "assistant" ? turns[turns.length - 1].content : "";

  return (
    <Paper
      component="section"
      aria-labelledby="questions-heading"
      p={{ base: "md", sm: "lg" }}
      radius="lg"
      withBorder
      shadow="sm"
      h={{ base: "auto", lg: "100%" }}
    >
      <Stack gap="md" h="100%">
        <Group justify="space-between" wrap="wrap" gap="sm">
          <Group gap="xs">
            <Title order={2} id="questions-heading" size="h4">
              Application questions
            </Title>
            <Badge variant="light" color="teal" leftSection={<IconSparkles size={12} />}>
              AI (OpenAI)
            </Badge>
          </Group>
          {turns.length > 0 && (
            <Button
              size="xs"
              variant="subtle"
              leftSection={<IconRefresh size={14} />}
              disabled={streaming}
              onClick={() => {
                setTurns([]);
                setError(null);
              }}
            >
              New chat
            </Button>
          )}
        </Group>

        <ScrollArea type="auto" offsetScrollbars h={height} scrollbarSize={8} viewportRef={viewportRef}>
          {turns.length === 0 ? (
            <Stack align="center" gap="sm" py="xl">
              <ThemeIcon size={56} radius="xl" variant="light" color="gray">
                <IconMessageQuestion size={28} stroke={1.25} />
              </ThemeIcon>
              <Text ta="center" maw={420} c="dimmed" size="sm">
                Paste a question from the application form. The answer is written from your resume and tailored to
                the job description. Anything your resume can't tell (like salary) is left as a [placeholder].
              </Text>
              <Group justify="center" gap={6} maw={520}>
                {EXAMPLES.map((ex) => (
                  <Button key={ex} size="compact-xs" variant="default" radius="xl" onClick={() => ask(ex)}>
                    {ex}
                  </Button>
                ))}
              </Group>
            </Stack>
          ) : (
            <Stack gap="md" pr="xs">
              {turns.map((t, i) =>
                t.role === "user" ? (
                  <Box key={i} style={{ alignSelf: "flex-end", maxWidth: "85%" }}>
                    <Paper radius="md" p="sm" bg="teal.9">
                      <Text size="sm" style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                        {t.content}
                      </Text>
                    </Paper>
                  </Box>
                ) : (
                  <Paper key={i} radius="md" p="sm" withBorder bg="dark.7">
                    <Group justify="space-between" align="flex-start" wrap="nowrap" gap="xs">
                      <Text
                        size="sm"
                        c="gray.1"
                        style={{ whiteSpace: "pre-wrap", wordBreak: "break-word", lineHeight: 1.7, flex: 1 }}
                      >
                        {t.content || (streaming && i === turns.length - 1 ? "Thinking…" : "")}
                      </Text>
                      {t.content && !(streaming && i === turns.length - 1) && (
                        <Tooltip label="Copy answer">
                          <ActionIcon variant="subtle" color="teal" onClick={() => copy(t.content)} aria-label="Copy answer">
                            <IconCopy size={16} />
                          </ActionIcon>
                        </Tooltip>
                      )}
                    </Group>
                  </Paper>
                ),
              )}
            </Stack>
          )}
        </ScrollArea>

        {error ? (
          <Alert variant="light" color="red" title="Could not answer" icon={<IconAlertCircle size={18} />}>
            {error}
          </Alert>
        ) : null}

        {lastAnswer && !streaming && (
          <Group gap={6}>
            {FOLLOW_UPS.map((f) => (
              <Button key={f} size="compact-xs" variant="default" radius="xl" onClick={() => ask(f)}>
                {f}
              </Button>
            ))}
          </Group>
        )}

        <Stack gap="xs">
          <Textarea
            placeholder={turns.length ? "Ask another question or a follow-up…" : "Paste the application question…"}
            value={draft}
            onChange={(e) => setDraft(e.currentTarget.value)}
            onKeyDown={(e) => {
              // Enter sends, Shift+Enter adds a new line (like ChatGPT).
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                void ask(draft);
              }
            }}
            autosize
            minRows={2}
            maxRows={8}
            disabled={streaming}
          />
          <Group justify="space-between" wrap="wrap" gap="xs">
            <SegmentedControl
              size="xs"
              value={length}
              onChange={(v) => setLength(v as AnswerLength)}
              data={[
                { value: "concise", label: "Concise" },
                { value: "standard", label: "Standard" },
                { value: "detailed", label: "Detailed" },
              ]}
            />
            {streaming ? (
              <Button
                size="sm"
                color="gray"
                leftSection={<IconPlayerStopFilled size={14} />}
                onClick={() => abortRef.current?.abort()}
              >
                Stop
              </Button>
            ) : (
              <Button
                size="sm"
                leftSection={<IconSend size={16} />}
                disabled={!draft.trim()}
                onClick={() => ask(draft)}
                variant="gradient"
                gradient={{ from: "teal", to: "cyan", deg: 105 }}
              >
                Get answer
              </Button>
            )}
          </Group>
          <Text size="xs" c="dimmed">
            {file
              ? `Using ${file.name}${jobDescription.trim() ? " and the job description" : " (add the job description for tailored answers)"}.`
              : "No resume attached — your saved base resume is used if you have one."}{" "}
            Enter to send, Shift+Enter for a new line.
          </Text>
        </Stack>
      </Stack>
    </Paper>
  );
}
