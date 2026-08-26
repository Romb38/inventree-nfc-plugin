import type { InvenTreePluginContext } from '@inventreedb/ui';
import { t } from '@lingui/core/macro';
import {
  Alert,
  Button,
  Group,
  NumberInput,
  Stack,
  Text,
  TextInput,
  Title
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useEffect, useState } from 'react';
import { LocalizedComponent } from './locale';
import {
  getEffectiveConfig,
  readWorkstationOverrides,
  writeWorkstationOverrides
} from './agentConfig';

function PluginSettingsDisplay({
  context
}: {
  context: InvenTreePluginContext;
}) {
  // The global defaults (from the server), shown as placeholders.
  const [globalUrl, setGlobalUrl] = useState<string>('');
  const [globalTimeout, setGlobalTimeout] = useState<number>(30);

  // The per-workstation overrides (localStorage).
  const [url, setUrl] = useState<string>('');
  const [timeout, setTimeout] = useState<number | string>('');

  useEffect(() => {
    // Load global config for reference/placeholders.
    context.api
      .get('/plugin/nfc/config/')
      .then((r: any) => {
        setGlobalUrl(r.data?.agent_base_url ?? '');
        setGlobalTimeout(r.data?.scan_timeout_seconds ?? 30);
      })
      .catch(() => {});
    // Load existing per-workstation overrides.
    const ov = readWorkstationOverrides();
    setUrl(ov.agent_base_url ?? '');
    setTimeout(ov.scan_timeout_seconds ?? '');
  }, [context.api]);

  function save() {
    writeWorkstationOverrides({
      agent_base_url: url.trim() || null,
      scan_timeout_seconds:
        timeout === '' || timeout == null ? null : Number(timeout)
    });
    notifications.show({
      title: t`Saved`,
      message: t`This workstation's agent settings were saved on this machine.`,
      color: 'green'
    });
  }

  function reset() {
    writeWorkstationOverrides({ agent_base_url: null, scan_timeout_seconds: null });
    setUrl('');
    setTimeout('');
    notifications.show({
      title: t`Reset`,
      message: t`This workstation now uses the default settings.`,
      color: 'blue'
    });
  }

  async function testConnection() {
    try {
      const cfg = await getEffectiveConfig(context.api);
      const res = await fetch(`${cfg.agent_base_url}/health`);
      const data = await res.json();
      if (data?.reader_connected) {
        notifications.show({
          title: t`Reader connected`,
          message: cfg.agent_base_url,
          color: 'green'
        });
      } else {
        notifications.show({
          title: t`Agent reachable, no reader`,
          message: t`The agent responded but no reader is connected.`,
          color: 'orange'
        });
      }
    } catch {
      notifications.show({
        title: t`Cannot reach agent`,
        message: t`Check the URL and that the agent is running on this workstation.`,
        color: 'red'
      });
    }
  }

  return (
    <Stack gap='md' maw={520}>
      <div>
        <Title order={4}>{t`Agent settings (this workstation)`}</Title>
        <Text size='sm' c='dimmed'>
          {t`These settings apply only to this computer. Leave a field empty to use the default.`}
        </Text>
      </div>

      <TextInput
        label={t`Agent URL (this workstation)`}
        description={t`Where the local NFC agent runs on this machine.`}
        placeholder={globalUrl || 'http://localhost:8765'}
        value={url}
        onChange={(e) => setUrl(e.currentTarget.value)}
      />

      <NumberInput
        label={t`Scan timeout (seconds)`}
        description={t`How long to wait for a tag before giving up.`}
        placeholder={String(globalTimeout)}
        min={1}
        max={120}
        value={timeout}
        onChange={setTimeout}
      />

      <Group>
        <Button color='teal' onClick={save}>{t`Save for this workstation`}</Button>
        <Button variant='default' onClick={testConnection}>{t`Test connection`}</Button>
        <Button variant='subtle' color='red' onClick={reset}>{t`Reset to default`}</Button>
      </Group>

      <Alert color='blue' variant='light'>
        <Text size='xs'>
          {t`If left empty, this workstation uses the built-in default:`}
        </Text>
        <Text size='xs'>
          {globalUrl || 'http://localhost:8765'} · {globalTimeout}s
        </Text>
      </Alert>
    </Stack>
  );
}

export function renderPluginSettings(context: InvenTreePluginContext) {
  return (
    <LocalizedComponent locale={context.locale} context={context}>
      <PluginSettingsDisplay context={context} />
    </LocalizedComponent>
  );
}
