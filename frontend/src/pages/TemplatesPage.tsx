import {
  Badge,
  Box,
  Button,
  Container,
  Grid,
  Group,
  Modal,
  Paper,
  Stack,
  Text,
  Title,
  rem,
} from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { notifications } from "@mantine/notifications";
import { IconCheck, IconEye, IconFileCv, IconLock } from "@tabler/icons-react";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { cvTemplateApi, getStoredToken, type CvTemplate } from "../auth/api";
import { useAuth } from "../auth/AuthContext";
import { CvTemplatePreview } from "../components/CvTemplatePreview";

export default function TemplatesPage() {
  const { user, refreshUser } = useAuth();
  const [templates, setTemplates] = useState<CvTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [selecting, setSelecting] = useState<string | null>(null);
  const [previewTemplate, setPreviewTemplate] = useState<CvTemplate | null>(null);
  const [previewPdfUrl, setPreviewPdfUrl] = useState<string | null>(null);
  const [previewOpen, { open: openPreview, close: closePreview }] = useDisclosure(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await cvTemplateApi.list();
      setTemplates(data);
    } catch (e) {
      notifications.show({
        title: "Could not load templates",
        message: e instanceof Error ? e.message : "Try again.",
        color: "red",
      });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    return () => {
      if (previewPdfUrl) URL.revokeObjectURL(previewPdfUrl);
    };
  }, [previewPdfUrl]);

  const openSamplePreview = async (template: CvTemplate) => {
    setPreviewTemplate(template);
    if (previewPdfUrl) URL.revokeObjectURL(previewPdfUrl);
    setPreviewPdfUrl(null);
    openPreview();
    try {
      const token = getStoredToken();
      const res = await fetch(cvTemplateApi.previewPdfUrl(template.key), {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!res.ok) throw new Error("Could not load sample PDF.");
      const blob = await res.blob();
      setPreviewPdfUrl(URL.createObjectURL(blob));
    } catch (e) {
      notifications.show({
        title: "Preview failed",
        message: e instanceof Error ? e.message : "Try again.",
        color: "orange",
      });
    }
  };

  const closeSamplePreview = () => {
    closePreview();
    setPreviewTemplate(null);
    if (previewPdfUrl) URL.revokeObjectURL(previewPdfUrl);
    setPreviewPdfUrl(null);
  };

  const selectTemplate = async (template: CvTemplate) => {
    if (template.status === "taken") return;
    if (template.status === "yours") return;
    setSelecting(template.key);
    try {
      const res = await cvTemplateApi.select(template.key);
      await refreshUser();
      await load();
      notifications.show({
        title: yours ? "Template switched" : "Template selected",
        message: res.message,
        color: "teal",
      });
    } catch (e) {
      notifications.show({
        title: "Could not select template",
        message: e instanceof Error ? e.message : "Try again.",
        color: "red",
      });
      await load();
    } finally {
      setSelecting(null);
    }
  };

  const yours = user?.cv_template_key;

  return (
    <Container size="lg" py={{ base: "md", sm: "xl" }} px={{ base: "sm", md: "md" }}>
      <Modal
        opened={previewOpen}
        onClose={closeSamplePreview}
        title={previewTemplate ? `Sample PDF — ${previewTemplate.label}` : "Sample preview"}
        size="xl"
        centered
      >
        {previewPdfUrl ? (
          <Box
            component="iframe"
            src={previewPdfUrl}
            title="CV template sample"
            style={{ width: "100%", height: "min(70dvh, 640px)", border: 0, borderRadius: rem(8) }}
          />
        ) : (
          <Stack align="center" py="xl" gap="sm">
            <Text c="dimmed" size="sm">
              Loading sample PDF…
            </Text>
          </Stack>
        )}
      </Modal>

      <Stack gap="lg">
        <Stack gap={4}>
          <Group gap="xs">
            <IconFileCv size={24} stroke={1.5} />
            <Title order={2}>Choose your CV template</Title>
          </Group>
          <Text c="dimmed" size="sm" maw={680}>
            Browse 40 smart resume layouts with mini previews. Click <strong>View sample PDF</strong> for the full example.
            Each member holds one template at a time; switch anytime to another available design.
          </Text>
        </Stack>

        {yours ? (
          <Paper withBorder radius="md" p="md" bg="dark.7">
            <Group justify="space-between" wrap="wrap" gap="sm">
              <Text size="sm">
                Your template:{" "}
                <Text component="span" fw={600}>
                  {user?.cv_template_label || yours}
                </Text>
              </Text>
              <Button component={Link} to="/builder" color="teal" size="sm">
                Open resume builder
              </Button>
            </Group>
          </Paper>
        ) : null}

        <Grid gutter="md">
          {templates.map((template) => {
            const isYours = template.status === "yours";
            const isTaken = template.status === "taken";
            const isCurrent = isYours;
            const canSelect = template.status === "available";
            return (
              <Grid.Col key={template.key} span={{ base: 12, sm: 6, md: 4, lg: 3 }}>
                <Paper
                  withBorder
                  radius="lg"
                  p="md"
                  bg="dark.7"
                  style={{
                    height: "100%",
                    opacity: isTaken ? 0.55 : 1,
                    borderColor: isYours ? "var(--mantine-color-teal-filled)" : undefined,
                  }}
                >
                  <Stack gap="sm" justify="space-between" h="100%">
                    <Stack gap="sm">
                      <Box
                        style={{ cursor: "pointer" }}
                        onClick={() => void openSamplePreview(template)}
                        title="View full sample PDF"
                      >
                        <CvTemplatePreview
                          templateKey={template.key}
                          accentColor={template.accent_color}
                          layoutFamily={template.layout_family}
                        />
                      </Box>
                      <Group justify="space-between" align="flex-start" wrap="nowrap" gap="xs">
                        <Text fw={700} size="sm" lineClamp={2}>
                          {template.label}
                        </Text>
                        {isYours ? (
                          <Badge color="teal" variant="light" size="sm">
                            Yours
                          </Badge>
                        ) : isTaken ? (
                          <Badge color="gray" variant="light" size="sm" leftSection={<IconLock size={12} />}>
                            Taken
                          </Badge>
                        ) : (
                          <Badge color="cyan" variant="outline" size="sm">
                            Available
                          </Badge>
                        )}
                      </Group>
                      <Text size="xs" c="dimmed" lineClamp={2}>
                        {template.description}
                      </Text>
                      <Button
                        variant="subtle"
                        color="gray"
                        size="compact-xs"
                        leftSection={<IconEye size={14} />}
                        onClick={() => void openSamplePreview(template)}
                      >
                        View sample PDF
                      </Button>
                    </Stack>
                    <Button
                      color="teal"
                      variant={isCurrent ? "light" : "filled"}
                      fullWidth
                      disabled={!canSelect || loading}
                      loading={selecting === template.key}
                      onClick={() => void selectTemplate(template)}
                    >
                      {isCurrent
                        ? "Current template"
                        : isTaken
                          ? "Taken by member"
                          : yours
                            ? "Switch to this"
                            : "Select template"}
                    </Button>
                  </Stack>
                </Paper>
              </Grid.Col>
            );
          })}
        </Grid>

        {!loading && templates.length === 0 ? (
          <Text ta="center" c="dimmed" py="xl">
            No templates available.
          </Text>
        ) : null}

        {yours ? (
          <Group justify="center">
            <IconCheck size={16} color="var(--mantine-color-teal-5)" />
            <Text size="sm" c="dimmed">
              One template at a time — pick another available design anytime to switch.
            </Text>
          </Group>
        ) : null}
      </Stack>
    </Container>
  );
}
