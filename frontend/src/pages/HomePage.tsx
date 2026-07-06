import {
  Accordion,
  ActionIcon,
  Alert,
  Badge,
  Button,
  Checkbox,
  Container,
  Divider,
  Group,
  List,
  Paper,
  rem,
  ScrollArea,
  SimpleGrid,
  Stack,
  Text,
  Textarea,
  TextInput,
  ThemeIcon,
  Title,
  Tooltip,
} from "@mantine/core";
import { useDisclosure, useMediaQuery } from "@mantine/hooks";
import { notifications } from "@mantine/notifications";
import { Dropzone } from "@mantine/dropzone";
import {
  IconAlertCircle,
  IconBriefcase,
  IconCheck,
  IconCopy,
  IconDownload,
  IconEye,
  IconFileCv,
  IconSparkles,
  IconUpload,
  IconUser,
  IconWriting,
  IconX,
} from "@tabler/icons-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { tailorApi, type TailorResponse } from "../auth/api";

import {
  parseExperienceCardMeta,
  segmentLabeledSkills,
  splitExperienceBlocks,
  splitSkillsParts,
} from "../formatResumeSections";

const ACCEPT = ["application/vnd.openxmlformats-officedocument.wordprocessingml.document"];

export default function HomePage() {
  const [file, setFile] = useState<File | null>(null);
  const [jobDescription, setJobDescription] = useState("");
  const [targetJobRole, setTargetJobRole] = useState("");
  const [enableBold, setEnableBold] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<TailorResponse | null>(null);
  const [resultPanelOpen, { open: openResultPanel, toggle: toggleResultPanel }] = useDisclosure(true);
  const [tailoredDocxUrl, setTailoredDocxUrl] = useState<string | null>(null);
  const [tailoredPdfUrl, setTailoredPdfUrl] = useState<string | null>(null);
  const isNarrow = useMediaQuery("(max-width: 62em)");

  useEffect(() => {
    if (!result?.docx_base64) {
      setTailoredDocxUrl(null);
      return;
    }
    try {
      const binary = atob(result.docx_base64);
      const len = binary.length;
      const bytes = new Uint8Array(len);
      for (let i = 0; i < len; i += 1) bytes[i] = binary.charCodeAt(i);
      const blob = new Blob([bytes], {
        type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      });
      const url = URL.createObjectURL(blob);
      setTailoredDocxUrl(url);
      return () => URL.revokeObjectURL(url);
    } catch {
      setTailoredDocxUrl(null);
    }
  }, [result?.docx_base64]);

  useEffect(() => {
    if (!result?.pdf_base64) {
      setTailoredPdfUrl(null);
      return;
    }
    try {
      const binary = atob(result.pdf_base64);
      const len = binary.length;
      const bytes = new Uint8Array(len);
      for (let i = 0; i < len; i += 1) bytes[i] = binary.charCodeAt(i);
      const blob = new Blob([bytes], { type: "application/pdf" });
      const url = URL.createObjectURL(blob);
      setTailoredPdfUrl(url);
      return () => URL.revokeObjectURL(url);
    } catch {
      setTailoredPdfUrl(null);
    }
  }, [result?.pdf_base64]);

  const canSubmit = useMemo(
    () =>
      Boolean(
        file &&
          jobDescription.trim().length > 20 &&
          targetJobRole.trim().length > 2,
      ),
    [file, jobDescription, targetJobRole],
  );

  const onRejectFiles = useCallback(() => {
    notifications.show({
      title: "Unsupported file",
      message: "Use a Word resume (.docx, max 15 MB).",
      color: "red",
      icon: <IconX size={18} />,
    });
  }, []);

  const onSubmit = useCallback(async () => {
    if (!file) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const data = await tailorApi.tailor(file, jobDescription, targetJobRole.trim(), enableBold);
      setResult(data);
      if (isNarrow) openResultPanel();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong.");
    } finally {
      setLoading(false);
    }
  }, [file, jobDescription, targetJobRole, enableBold, isNarrow, openResultPanel]);

  const copyResult = async () => {
    if (!result) return;
    try {
      await navigator.clipboard.writeText(result.tailored_resume);
      notifications.show({
        title: "Copied",
        message: "Full resume text is on your clipboard.",
        color: "teal",
        icon: <IconCheck size={18} />,
      });
    } catch {
      notifications.show({
        title: "Copy failed",
        message: "Your browser blocked clipboard access.",
        color: "orange",
      });
    }
  };

  const copySection = async (text: string, sectionLabel: string) => {
    try {
      await navigator.clipboard.writeText(text);
      notifications.show({
        title: "Copied",
        message: `${sectionLabel} copied to clipboard.`,
        color: "teal",
        icon: <IconCheck size={18} />,
      });
    } catch {
      notifications.show({
        title: "Copy failed",
        message: "Your browser blocked clipboard access.",
        color: "orange",
      });
    }
  };

  const resultHeight = { base: "min(52dvh, 420px)", sm: "min(58dvh, 520px)", lg: "min(68dvh, 640px)" };

  const experienceBlocks = useMemo(
    () => splitExperienceBlocks(result?.tailored_experience ?? ""),
    [result?.tailored_experience],
  );

  const skillsDisplay = useMemo(() => {
    const raw = result?.tailored_skills ?? "";
    const parts = splitSkillsParts(raw);
    const segments = segmentLabeledSkills(parts.body);
    return { parts, segments };
  }, [result?.tailored_skills]);

  const docxExportPanel =
    result && tailoredDocxUrl ? (
      <Paper withBorder radius="md" p="md" bg="dark.7">
        <Stack gap="sm">
          <Stack gap={4}>
            <Text fw={600} size="sm">
              Your tailored resume
            </Text>
            <Text size="xs" c="dimmed" maw={520}>
              Built from your uploaded .docx template. Text is updated in place so fonts, spacing, and layout stay the same.
            </Text>
          </Stack>
          <Group gap="sm">
            <Button
              component="a"
              href={tailoredDocxUrl}
              download={result.download_filename || "resume-tailored.docx"}
              leftSection={<IconDownload size={18} />}
              variant="filled"
              color="teal"
              size="sm"
            >
              Download Word (.docx)
            </Button>
            {tailoredPdfUrl ? (
              <Button
                component="a"
                href={tailoredPdfUrl}
                download={result.pdf_download_filename || "resume-tailored.pdf"}
                leftSection={<IconDownload size={18} />}
                variant="light"
                color="teal"
                size="sm"
              >
                Download PDF
              </Button>
            ) : null}
          </Group>
          {!tailoredPdfUrl ? (
            <Text size="xs" c="dimmed">
              PDF conversion requires Microsoft Word or LibreOffice on the server. The Word file is always available.
            </Text>
          ) : null}
        </Stack>
      </Paper>
    ) : result && !tailoredDocxUrl ? (
      <Alert variant="light" color="orange" title="Word export unavailable" icon={<IconAlertCircle size={18} />}>
        Tailored text sections were generated, but the .docx could not be updated. Add clear section headers (Summary,
        Experience, Skills, Education) to your template and try again.
      </Alert>
    ) : null;

  const inputColumn = (
    <Paper
      component="section"
      aria-labelledby="inputs-heading"
      p={{ base: "md", sm: "lg" }}
      radius="lg"
      withBorder
      shadow="sm"
    >
      <Stack gap="md">
        <Group justify="space-between" wrap="nowrap" gap="sm">
          <Title order={2} id="inputs-heading" size="h4">
            Inputs
          </Title>
          {isNarrow && result ? (
            <Button variant="light" size="xs" onClick={toggleResultPanel}>
              {resultPanelOpen ? "Hide result" : "Show result"}
            </Button>
          ) : null}
        </Group>

        <Dropzone
          onDrop={(files) => {
            setFile(files[0]);
            setError(null);
          }}
          onReject={onRejectFiles}
          maxSize={15 * 1024 ** 2}
          maxFiles={1}
          accept={ACCEPT}
          multiple={false}
          radius="md"
          styles={{
            root: {
              minHeight: isNarrow ? rem(140) : rem(160),
            },
          }}
        >
          <Group justify="center" gap="xl" mih={120} style={{ pointerEvents: "none" }}>
            <Dropzone.Accept>
              <ThemeIcon size={56} radius="xl" color="teal" variant="light">
                <IconUpload size={28} stroke={1.5} />
              </ThemeIcon>
            </Dropzone.Accept>
            <Dropzone.Reject>
              <ThemeIcon size={56} radius="xl" color="red" variant="light">
                <IconX size={28} stroke={1.5} />
              </ThemeIcon>
            </Dropzone.Reject>
            <Dropzone.Idle>
              <ThemeIcon size={56} radius="xl" color="gray" variant="light">
                <IconFileCv size={28} stroke={1.5} />
              </ThemeIcon>
            </Dropzone.Idle>
            <Stack gap={4} miw={0} style={{ flex: 1 }}>
              <Text size="sm" fw={600} ta={{ base: "center", xs: "left" }}>
                Drop your resume here
              </Text>
              <Text size="xs" c="dimmed" ta={{ base: "center", xs: "left" }} lineClamp={3}>
                Word resume (.docx) — your file is the layout template
              </Text>
            </Stack>
          </Group>
        </Dropzone>

        {file ? (
          <Group justify="space-between" wrap="nowrap" gap="xs">
            <Text size="sm" truncate title={file.name} style={{ flex: 1 }}>
              <Text span fw={500}>
                Selected:
              </Text>{" "}
              {file.name}
            </Text>
            <Button variant="default" size="compact-sm" onClick={() => setFile(null)}>
              Clear
            </Button>
          </Group>
        ) : null}

        {file ? (
          <Accordion variant="contained" radius="md" defaultValue="upload-preview">
            <Accordion.Item value="upload-preview">
              <Accordion.Control>
                <Group gap="xs" wrap="nowrap">
                  <ThemeIcon size="sm" variant="light" color="gray" radius="sm">
                    <IconEye size={16} stroke={1.5} />
                  </ThemeIcon>
                  <Text fw={600} size="sm">
                    Uploaded resume preview
                  </Text>
                </Group>
              </Accordion.Control>
              <Accordion.Panel>
                <Alert color="gray" variant="light" title="Your .docx is the template">
                  Upload a Word resume with clear section headings. After generating, download your template with headline,
                  summary, experience, skills, education, and extras rewritten for the job.
                </Alert>
              </Accordion.Panel>
            </Accordion.Item>
          </Accordion>
        ) : null}

        <TextInput
          label="Target job role"
          description="Required. Used as the job title on every work experience entry (e.g. Senior AI Engineer)."
          placeholder="Senior AI Engineer"
          value={targetJobRole}
          onChange={(e) => {
            setTargetJobRole(e.target.value);
            setError(null);
          }}
          required
          size="md"
        />

        <Textarea
          label="Job description"
          description="Paste the full posting — richer text yields better keyword alignment."
          placeholder="Responsibilities, requirements, tools, seniority…"
          value={jobDescription}
          onChange={(e) => {
            setJobDescription(e.target.value);
            setError(null);
          }}
          autosize
          minRows={isNarrow ? 10 : 12}
          maxRows={24}
          size="md"
        />

        <Stack gap="sm">
          <Checkbox
            label="Bold important keywords in the Word download"
            description="Highlights JD-critical terms in Profile, Experience, and top Skills. Uncheck for plain text only."
            checked={enableBold}
            onChange={(e) => setEnableBold(e.currentTarget.checked)}
          />
          <Button
            fullWidth
            size="md"
            leftSection={<IconSparkles size={20} />}
            disabled={!canSubmit || loading}
            loading={loading}
            onClick={onSubmit}
            variant="gradient"
            gradient={{ from: "teal", to: "cyan", deg: 105 }}
          >
            {loading ? "Tailoring…" : "Generate tailored resume"}
          </Button>
          {!canSubmit && !loading ? (
            <Text size="xs" c="dimmed" ta="center">
              Add a .docx resume, target job role, and a job description (20+ characters) to generate.
            </Text>
          ) : null}
        </Stack>

        {error ? (
          <Alert variant="light" color="red" title="Could not tailor resume" icon={<IconAlertCircle size={18} />}>
            {error}
          </Alert>
        ) : null}
      </Stack>
    </Paper>
  );

  const resultColumnFull =
    result && (!isNarrow || resultPanelOpen) ? (
      <Paper
        component="section"
        aria-labelledby="result-heading"
        p={{ base: "md", sm: "lg" }}
        radius="lg"
        withBorder
        shadow="sm"
        h={{ base: "auto", lg: "100%" }}
        style={{ minHeight: 0 }}
      >
        <Stack gap="md" h="100%">
          <Group justify="space-between" align="flex-start" wrap="wrap" gap="sm">
            <Title order={2} id="result-heading" size="h4">
              Result
            </Title>
            <Group gap="xs" wrap="wrap">
              <Badge
                size="lg"
                variant="light"
                color={result.used_llm ? "teal" : "gray"}
                leftSection={result.used_llm ? <IconSparkles size={14} /> : undefined}
              >
                {result.used_llm ? "AI (OpenAI)" : "Offline + keywords"}
              </Badge>
              <Tooltip label="Copy full assembled resume">
                <ActionIcon variant="filled" color="teal" size="lg" radius="md" onClick={copyResult} aria-label="Copy full">
                  <IconCopy size={18} />
                </ActionIcon>
              </Tooltip>
            </Group>
          </Group>

          {result.keywords_highlighted.length > 0 ? (
            <Group gap={6} wrap="wrap" aria-label="Keywords from job description">
              {result.keywords_highlighted.slice(0, 20).map((k) => (
                <Badge key={k} variant="outline" color="gray" size="sm">
                  {k}
                </Badge>
              ))}
            </Group>
          ) : null}

          {docxExportPanel}

          <Stack gap="md">
            <Paper withBorder radius="md" p="md" bg="dark.7">
              <Group justify="space-between" align="flex-start" wrap="nowrap" gap="sm" mb="xs">
                <Group gap="xs">
                  <ThemeIcon size={36} radius="md" variant="light" color="yellow">
                    <IconFileCv size={20} stroke={1.25} />
                  </ThemeIcon>
                  <Title order={3} size="h5">
                    Header / title
                  </Title>
                </Group>
                <Tooltip label="Copy header">
                  <ActionIcon
                    variant="light"
                    color="yellow"
                    size="lg"
                    radius="md"
                    onClick={() => copySection(result.tailored_contact, "Header")}
                    aria-label="Copy header"
                    disabled={!result.tailored_contact?.trim()}
                  >
                    <IconCopy size={18} />
                  </ActionIcon>
                </Tooltip>
              </Group>
              <Text size="sm" c="gray.1" style={{ whiteSpace: "pre-wrap", lineHeight: 1.65 }}>
                {result.tailored_contact?.trim() || "—"}
              </Text>
            </Paper>

            <Paper withBorder radius="md" p="md" bg="dark.7">
              <Group justify="space-between" align="flex-start" wrap="nowrap" gap="sm" mb="xs">
                <Group gap="xs">
                  <ThemeIcon size={36} radius="md" variant="light" color="teal">
                    <IconUser size={20} stroke={1.25} />
                  </ThemeIcon>
                  <Title order={3} size="h5">
                    Professional summary
                  </Title>
                </Group>
                <Tooltip label="Copy profile">
                  <ActionIcon
                    variant="light"
                    color="teal"
                    size="lg"
                    radius="md"
                    onClick={() => copySection(result.tailored_summary, "Profile")}
                    aria-label="Copy profile"
                    disabled={!result.tailored_summary?.trim()}
                  >
                    <IconCopy size={18} />
                  </ActionIcon>
                </Tooltip>
              </Group>
              <Text size="sm" c="gray.1" style={{ whiteSpace: "pre-wrap", lineHeight: 1.65 }}>
                {result.tailored_summary?.trim() || "—"}
              </Text>
            </Paper>

            <Paper withBorder radius="md" p="md" bg="dark.7">
              <Group justify="space-between" align="flex-start" wrap="nowrap" gap="sm" mb="xs">
                <Group gap="xs">
                  <ThemeIcon size={36} radius="md" variant="light" color="cyan">
                    <IconBriefcase size={20} stroke={1.25} />
                  </ThemeIcon>
                  <Title order={3} size="h5">
                    Experience
                  </Title>
                </Group>
                <Tooltip label={experienceBlocks.length > 1 ? "Copy all positions (plain text)" : "Copy experience"}>
                  <ActionIcon
                    variant="light"
                    color="cyan"
                    size="lg"
                    radius="md"
                    onClick={() => copySection(result.tailored_experience, "Experience")}
                    aria-label="Copy experience"
                    disabled={!result.tailored_experience?.trim()}
                  >
                    <IconCopy size={18} />
                  </ActionIcon>
                </Tooltip>
              </Group>
              <ScrollArea type="auto" offsetScrollbars h={{ base: "min(44dvh, 380px)", sm: "min(52dvh, 480px)" }} scrollbarSize={8}>
                <Stack gap="sm">
                  {(experienceBlocks.length ? experienceBlocks : []).map((block, i) => {
                    const meta = parseExperienceCardMeta(block);
                    const detail =
                      meta.detailBody.trim().length > 0 ? meta.detailBody : block;
                    return (
                      <Paper
                        key={`exp-${i}`}
                        withBorder
                        p="sm"
                        radius="sm"
                        bg="dark.8"
                        style={{
                          borderLeftWidth: 4,
                          borderLeftStyle: "solid",
                          borderLeftColor: "var(--mantine-color-cyan-filled)",
                        }}
                      >
                        <Group justify="space-between" align="flex-start" wrap="nowrap" gap="xs" mb={8}>
                          <Text size="xs" tt="uppercase" fw={600} c="cyan.4">
                            {experienceBlocks.length > 1 ? `Position ${i + 1}` : "Experience"}
                          </Text>
                          <Tooltip
                            label={
                              experienceBlocks.length > 1 ? `Copy position ${i + 1} only` : "Copy this block"
                            }
                          >
                            <ActionIcon
                              variant="subtle"
                              color="cyan"
                              size="sm"
                              radius="md"
                              aria-label={`Copy position ${i + 1}`}
                              onClick={() =>
                                copySection(block, experienceBlocks.length > 1 ? `Position ${i + 1}` : "Experience")
                              }
                            >
                              <IconCopy size={16} />
                            </ActionIcon>
                          </Tooltip>
                        </Group>
                        <Stack gap={6}>
                          <Text fw={700} size="sm" lh={1.35}>
                            {meta.titleLine || block.split(/\r?\n/).find((l) => l.trim()) || "—"}
                          </Text>
                          {(meta.companyLine || meta.periodLine || meta.locationLine) && (
                            <Group gap="xs" wrap="wrap" align="center">
                              {meta.companyLine ? (
                                <Text fw={600} size="sm" c="gray.2">
                                  {meta.companyLine}
                                </Text>
                              ) : null}
                              {meta.periodLine ? (
                                <Badge size="sm" variant="light" color="cyan">
                                  {meta.periodLine}
                                </Badge>
                              ) : null}
                              {meta.locationLine ? (
                                <Text size="xs" c="dimmed">
                                  {meta.locationLine}
                                </Text>
                              ) : null}
                            </Group>
                          )}
                          <Divider my={4} label="Details" labelPosition="center" />
                          <Text
                            component="pre"
                            fz="sm"
                            ff="inherit"
                            c="gray.1"
                            style={{
                              whiteSpace: "pre-wrap",
                              wordBreak: "break-word",
                              margin: 0,
                              lineHeight: 1.65,
                            }}
                          >
                            {detail}
                          </Text>
                        </Stack>
                      </Paper>
                    );
                  })}
                  {!experienceBlocks.length ? (
                    <Text size="sm" c="dimmed">
                      —
                    </Text>
                  ) : null}
                </Stack>
              </ScrollArea>
            </Paper>

            <Paper withBorder radius="md" p="md" bg="dark.7">
              <Group justify="space-between" align="flex-start" wrap="nowrap" gap="sm" mb="xs">
                <Group gap="xs">
                  <ThemeIcon size={36} radius="md" variant="light" color="grape">
                    <IconWriting size={20} stroke={1.25} />
                  </ThemeIcon>
                  <Title order={3} size="h5">
                    Skills
                  </Title>
                </Group>
                <Tooltip
                  label={
                    skillsDisplay.parts.postingHint ? "Copy skills + alignment note" : "Copy skills (full text)"
                  }
                >
                  <ActionIcon
                    variant="light"
                    color="grape"
                    size="lg"
                    radius="md"
                    onClick={() => copySection(result.tailored_skills, "Skills")}
                    aria-label="Copy skills"
                    disabled={!result.tailored_skills?.trim()}
                  >
                    <IconCopy size={18} />
                  </ActionIcon>
                </Tooltip>
              </Group>
              <Stack gap="sm">
                {skillsDisplay.segments.length > 0 ? (
                  skillsDisplay.segments.map((seg, i) => (
                    <Paper
                      key={`sk-${i}`}
                      withBorder
                      p="sm"
                      radius="sm"
                      bg="dark.8"
                      style={{
                        borderLeftWidth: 4,
                        borderLeftStyle: "solid",
                        borderLeftColor: "var(--mantine-color-grape-filled)",
                      }}
                    >
                      <Group justify="space-between" align="flex-start" wrap="nowrap" gap="xs">
                        <Text size="sm" c="gray.2" lh={1.65} style={{ flex: 1, minWidth: 0 }}>
                          <Text component="span" fw={700} c="gray.1">
                            {seg.label}:
                          </Text>{" "}
                          {seg.text}
                        </Text>
                        <Tooltip label={`Copy ${seg.label} line`}>
                          <ActionIcon
                            variant="subtle"
                            color="grape"
                            size="sm"
                            radius="md"
                            aria-label={`Copy ${seg.label}`}
                            onClick={() =>
                              copySection(`${seg.label}: ${seg.text}`, `${seg.label} (skills)`)
                            }
                          >
                            <IconCopy size={16} />
                          </ActionIcon>
                        </Tooltip>
                      </Group>
                    </Paper>
                  ))
                ) : skillsDisplay.parts.body.trim() ? (
                  <Text size="sm" c="gray.1" style={{ whiteSpace: "pre-wrap", lineHeight: 1.7 }}>
                    {skillsDisplay.parts.body}
                  </Text>
                ) : !skillsDisplay.parts.postingHint ? (
                  <Text size="sm" c="dimmed">
                    —
                  </Text>
                ) : null}
                {skillsDisplay.parts.postingHint ? (
                  <Paper withBorder p="sm" radius="sm" bg="dark.9" style={{ borderStyle: "dashed" }}>
                    <Group justify="space-between" align="flex-start" wrap="nowrap" gap="xs" mb={6}>
                      <div>
                        <Text size="xs" tt="uppercase" fw={600} c="dimmed">
                          Posting alignment hints
                        </Text>
                        <Text size="xs" c="dimmed">
                          Optional keywords to weave in only when accurate.
                        </Text>
                      </div>
                      <Tooltip label="Copy alignment hints only">
                        <ActionIcon
                          variant="subtle"
                          color="gray"
                          size="sm"
                          radius="md"
                          aria-label="Copy posting hints"
                          onClick={() =>
                            copySection(skillsDisplay.parts.postingHint ?? "", "Posting alignment hints")
                          }
                        >
                          <IconCopy size={16} />
                        </ActionIcon>
                      </Tooltip>
                    </Group>
                    <Text size="xs" c="dimmed" style={{ whiteSpace: "pre-wrap", lineHeight: 1.65 }}>
                      {skillsDisplay.parts.postingHint}
                    </Text>
                  </Paper>
                ) : null}
              </Stack>
            </Paper>

            {result.tailored_education?.trim() ? (
              <Paper withBorder radius="md" p="md" bg="dark.7">
                <Group justify="space-between" align="flex-start" wrap="nowrap" gap="sm" mb="xs">
                  <Title order={3} size="h5">
                    Education
                  </Title>
                  <Tooltip label="Copy education">
                    <ActionIcon
                      variant="light"
                      color="indigo"
                      size="lg"
                      radius="md"
                      onClick={() => copySection(result.tailored_education, "Education")}
                      aria-label="Copy education"
                    >
                      <IconCopy size={18} />
                    </ActionIcon>
                  </Tooltip>
                </Group>
                <Text size="sm" c="gray.1" style={{ whiteSpace: "pre-wrap", lineHeight: 1.65 }}>
                  {result.tailored_education}
                </Text>
              </Paper>
            ) : null}

            {result.tailored_other?.trim() ? (
              <Paper withBorder radius="md" p="md" bg="dark.7">
                <Group justify="space-between" align="flex-start" wrap="nowrap" gap="sm" mb="xs">
                  <Title order={3} size="h5">
                    Additional
                  </Title>
                  <Tooltip label="Copy additional sections">
                    <ActionIcon
                      variant="light"
                      color="gray"
                      size="lg"
                      radius="md"
                      onClick={() => copySection(result.tailored_other, "Additional")}
                      aria-label="Copy additional"
                    >
                      <IconCopy size={18} />
                    </ActionIcon>
                  </Tooltip>
                </Group>
                <Text size="sm" c="gray.1" style={{ whiteSpace: "pre-wrap", lineHeight: 1.65 }}>
                  {result.tailored_other}
                </Text>
              </Paper>
            ) : null}
          </Stack>

          <Accordion variant="contained" radius="md">
            <Accordion.Item value="full">
              <Accordion.Control>Full assembled resume (plain text)</Accordion.Control>
              <Accordion.Panel>
                <ScrollArea type="auto" offsetScrollbars h={resultHeight} scrollbarSize={8}>
                  <Text
                    component="pre"
                    fz="xs"
                    ff="monospace"
                    style={{
                      whiteSpace: "pre-wrap",
                      wordBreak: "break-word",
                      margin: 0,
                    }}
                  >
                    {result.tailored_resume}
                  </Text>
                </ScrollArea>
              </Accordion.Panel>
            </Accordion.Item>
          </Accordion>

          {result.ats_tips.length > 0 ? (
            <>
              <Divider label="ATS tips" labelPosition="left" />
              <List
                size="sm"
                spacing="xs"
                c="dimmed"
                icon={
                  <ThemeIcon size={20} radius="xl" variant="light" color="teal">
                    <IconCheck size={12} />
                  </ThemeIcon>
                }
              >
                {result.ats_tips.map((t) => (
                  <List.Item key={t}>{t}</List.Item>
                ))}
              </List>
            </>
          ) : null}
        </Stack>
      </Paper>
    ) : null;

  const resultColumnPlaceholder = !result ? (
    <Paper
      component="section"
      p={{ base: "md", sm: "xl" }}
      radius="lg"
      withBorder
      h={{ base: "auto", lg: "100%" }}
      style={{ alignContent: "center" }}
    >
      <Stack align="center" gap="sm" py={{ base: "xl", lg: "calc(8 * var(--mantine-spacing-xl))" }}>
        <ThemeIcon size={64} radius="xl" variant="light" color="gray">
          <IconFileCv size={32} stroke={1.25} />
        </ThemeIcon>
            <Text ta="center" maw={380} c="dimmed" size="sm">
                  Upload a Word resume (.docx), paste a job description, and get a complete resume tailored for that role.
        </Text>
      </Stack>
    </Paper>
  ) : null;

  const resultColumn = resultColumnFull ?? resultColumnPlaceholder;

  return (
    <Container size="xl" py={{ base: "md", sm: "lg", md: "xl" }} px={{ base: "sm", sm: "md" }}>
        {isNarrow && result && !resultPanelOpen ? (
          <Stack gap="md">{inputColumn}</Stack>
        ) : (
          <SimpleGrid cols={{ base: 1, lg: 2 }} spacing={{ base: "md", lg: "lg" }} verticalSpacing={{ base: "md", lg: "lg" }}>
            {inputColumn}
            {resultColumn}
          </SimpleGrid>
        )}

      </Container>
  );
}
