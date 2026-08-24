import type { InvenTreePluginContext } from '@inventreedb/ui';
import { t } from '@lingui/core/macro';
import {
  Alert,
  Box,
  Button,
  Group,
  Loader,
  Modal,
  NumberInput,
  Select,
  SegmentedControl,
  Stack,
  Text,
  TextInput
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { IconCheck, IconWifi } from '@tabler/icons-react';
import { useEffect, useState } from 'react';
import { playSound } from './sound';

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

interface NfcConfig {
  agent_base_url: string;
  scan_timeout_seconds: number;
  sound_enabled: boolean;
}

interface ScanResult {
  uid?: string;
  error?: string;
}

interface PartOption {
  value: string; // part id as string
  label: string; // part name
}

async function getReaderConnected(agentBaseUrl: string): Promise<boolean> {
  try {
    const res = await fetch(`${agentBaseUrl}/health`);
    if (!res.ok) return false;
    const data = await res.json();
    return !!data.reader_connected;
  } catch {
    return false;
  }
}

async function scanOnce(agentBaseUrl: string, timeoutSeconds: number): Promise<string> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), (timeoutSeconds + 2) * 1000);
  try {
    const res = await fetch(`${agentBaseUrl}/scan/once`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ timeout: timeoutSeconds }),
      signal: controller.signal
    });
    const data: ScanResult = await res.json().catch(() => ({}));
    if (res.ok && data.uid) return data.uid;
    throw new Error(data.error ?? `http_${res.status}`);
  } finally {
    clearTimeout(timer);
  }
}

// Reader status dot (color only, no text).
function ReaderDot({ connected }: { connected: boolean | null }) {
  return (
    <Box
      w={10}
      h={10}
      mb={10}
      style={{
        borderRadius: '999px',
        flexShrink: 0,
        backgroundColor:
          connected === null
            ? 'var(--mantine-color-yellow-6)'
            : connected
              ? 'var(--mantine-color-green-6)'
              : 'var(--mantine-color-red-6)'
      }}
    />
  );
}

// Hook: poll reader connection every 3s.
function useReaderStatus(context: InvenTreePluginContext) {
  const [connected, setConnected] = useState<boolean | null>(null);
  useEffect(() => {
    let active = true;
    let timer: number;
    let agentUrl: string | null = null;

    async function poll() {
      try {
        // Fetch config only once; the agent URL doesn't change.
        if (!agentUrl) {
          const r = await context.api.get('/plugin/nfc/config/');
          agentUrl = r.data.agent_base_url;
        }
        const ok = await getReaderConnected(agentUrl!);
        if (active) setConnected(ok);
      } catch {
        if (active) setConnected(false);
      }
      if (active) timer = window.setTimeout(poll, 5000);
    }
    poll();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [context.api]);
  return connected;
}

// ---------------------------------------------------------------------------
// CREATE PART form
// ---------------------------------------------------------------------------

export function CreatePartForm({
  context,
  onCreated
}: {
  context: InvenTreePluginContext;
  // Called after a part is created; receives the new part id + name so the
  // container can offer "add a unit?" and hand off to the item tab.
  onCreated?: (partId: number, partName: string) => void;
}) {
  const [molecule, setMolecule] = useState('');
  const [dosage, setDosage] = useState('');
  const [form, setForm] = useState<string | null>('Solution');
  const [laboratory, setLaboratory] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);

  const previewName = [molecule, laboratory, dosage, form]
    .map((s) => (s || '').trim())
    .filter(Boolean)
    .join(' ');

  const canSubmit =
    !!molecule.trim() && !!dosage.trim() && (form === 'Solution' || form === 'Poudre');

  async function doCreate() {
    setConfirmOpen(false);
    if (!canSubmit || submitting) return;
    setSubmitting(true);
    try {
      const res = await context.api.post('/plugin/nfc/create-product/', {
        molecule: molecule.trim(),
        dosage: dosage.trim(),
        form,
        laboratory: laboratory.trim(),
        add_unit: false // Part-only; the unit (with its container) is created in the Item tab.
      });
      const data = res.data;
      notifications.show({
        title: data.reused_existing_part ? t`Product already exists` : t`Product created`,
        message: data.reused_existing_part
          ? t`This product already exists — no new product was created.`
          : data.part_name,
        color: data.reused_existing_part ? 'yellow' : 'green'
      });
      // Reset product fields
      setMolecule('');
      setDosage('');
      setLaboratory('');
      setForm('Solution');
      // Only offer to add a unit when a NEW product was actually created.
      // If it already existed, the user should use the Unit tab instead;
      // prompting here would reward a mistaken re-entry.
      if (!data.reused_existing_part && onCreated) {
        onCreated(data.part_id, data.part_name);
      }
    } catch (err: any) {
      notifications.show({
        title: t`Creation failed`,
        message: err?.response?.data?.error ?? t`Could not create the product.`,
        color: 'red'
      });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Stack gap='sm'>
      <Modal
        opened={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        title={t`Confirm new product`}
        centered
        size='sm'
      >
        <Stack gap='sm'>
          <Text size='sm'>{t`Create this product?`}</Text>
          <Alert color='blue' variant='light' p='xs'>
            <Text size='sm' fw={600}>{previewName}</Text>
            <Text size='xs' c='dimmed'>
              {t`Molecule:`} {molecule} · {t`Dosage:`} {dosage} · {t`Form:`} {form}
              {laboratory ? ` · ${t`Lab:`} ${laboratory}` : ''}
            </Text>
          </Alert>
          <Group justify='flex-end' gap='xs'>
            <Button variant='default' size='xs' onClick={() => setConfirmOpen(false)}>
              {t`Cancel`}
            </Button>
            <Button size='xs' color='teal' loading={submitting} onClick={doCreate}>
              {t`Confirm`}
            </Button>
          </Group>
        </Stack>
      </Modal>

      <Text fw={600}>{t`Create product`}</Text>

      <TextInput
        label={t`Molecule (DCI)`}
        placeholder='Paracétamol'
        value={molecule}
        onChange={(e) => setMolecule(e.currentTarget.value)}
        required
      />
      <TextInput
        label={t`Dosage / concentration`}
        placeholder='10 mg/ml'
        value={dosage}
        onChange={(e) => setDosage(e.currentTarget.value)}
        required
      />
      <Select
        label={t`Form`}
        data={['Solution', 'Poudre']}
        value={form}
        onChange={setForm}
        required
      />
      <TextInput
        label={t`Laboratory`}
        placeholder='B. Braun'
        value={laboratory}
        onChange={(e) => setLaboratory(e.currentTarget.value)}
      />

      {previewName && (
        <Alert color='blue' variant='light' p='xs'>
          <Text size='xs' c='dimmed'>{t`Product name will be:`}</Text>
          <Text size='sm' fw={600}>{previewName}</Text>
        </Alert>
      )}

      <Button
        mt='xs'
        leftSection={<IconCheck size={16} />}
        disabled={!canSubmit}
        onClick={() => setConfirmOpen(true)}
      >
        {t`Add product`}
      </Button>
    </Stack>
  );
}

// ---------------------------------------------------------------------------
// CREATE ITEM form
// ---------------------------------------------------------------------------

export function CreateItemForm({
  context,
  presetPartId,
  onRequestCreatePart
}: {
  context: InvenTreePluginContext;
  // If provided, this part is preselected (used after creating a part).
  presetPartId?: number | null;
  // Called when the user chooses "Create new part" in the selector.
  onRequestCreatePart?: () => void;
}) {
  const [parts, setParts] = useState<PartOption[]>([]);
  const [partId, setPartId] = useState<string | null>(
    presetPartId ? String(presetPartId) : null
  );
  const [batch, setBatch] = useState('');
  const [serial, setSerial] = useState('');
  const [expiry, setExpiry] = useState('');
  const [received, setReceived] = useState('');
  const [quantity, setQuantity] = useState<number | string>(1);
  const [uid, setUid] = useState('');
  const [scanning, setScanning] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  // The selected part's form ("Solution" | "Poudre"), and the container the
  // user chooses for THIS unit (constrained by the form).
  const [partForm, setPartForm] = useState<string | null>(null);
  const [container, setContainer] = useState<string | null>(null);

  // Container options allowed for the part's form.
  const containerOptions =
    partForm === 'Poudre'
      ? ['Flacon poudre']
      : partForm === 'Solution'
        ? ['Ampoule', 'Poche']
        : ['Ampoule', 'Poche', 'Flacon poudre'];

  // Behaviour + unit derived from the CHOSEN container.
  const behaviour: 'whole' | 'quantity' =
    container === 'Poche' || container === 'Flacon poudre' ? 'quantity' : 'whole';
  const unitLabel = container === 'Poche' ? 'mL' : container === 'Flacon poudre' ? 'mg' : null;

  const readerConnected = useReaderStatus(context);

  // Load parts for the selector.
  useEffect(() => {
    let active = true;
    context.api
      .get('/api/part/?limit=500&ordering=name')
      .then((r) => {
        const results = r.data?.results ?? r.data ?? [];
        if (active) {
          setParts(
            results.map((p: any) => ({ value: String(p.pk), label: p.name }))
          );
        }
      })
      .catch(() => {
        if (active) setParts([]);
      });
    return () => {
      active = false;
    };
  }, [context.api]);

  // Keep preset in sync if it changes (e.g. after creating a part).
  useEffect(() => {
    if (presetPartId) setPartId(String(presetPartId));
  }, [presetPartId]);

  const CREATE_NEW = '__create_new__';
  const hasPart = !!partId && partId !== CREATE_NEW;
  const ready = hasPart && !!container;

  // When a part is chosen, fetch its form and default the container choice.
  useEffect(() => {
    if (!hasPart) {
      setPartForm(null);
      setContainer(null);
      return;
    }
    let active = true;
    context.api
      .get(`/plugin/nfc/part-info/${partId}/`)
      .then((r) => {
        if (!active) return;
        const f = r.data?.form ?? null;
        setPartForm(f);
        // Preselect the only valid container when the form dictates it.
        if (f === 'Poudre') setContainer('Flacon poudre');
        else setContainer(null); // Solution → let the user pick Ampoule/Poche
      })
      .catch(() => {
        if (active) {
          setPartForm(null);
          setContainer(null);
        }
      });
    return () => {
      active = false;
    };
  }, [partId, hasPart, context.api]);

  async function handleScan() {
    if (scanning) return;
    setScanning(true);
    try {
      const r = await context.api.get('/plugin/nfc/config/');
      const cfg: NfcConfig = r.data;
      playSound(cfg.sound_enabled, 'click');
      const scanned = await scanOnce(cfg.agent_base_url, cfg.scan_timeout_seconds);

      // Check if this tag is already linked to a unit, and warn right away.
      try {
        const check = await context.api.get(`/plugin/nfc/tag/${scanned}/`);
        if (check.data?.found) {
          playSound(cfg.sound_enabled, 'error');
          notifications.show({
            title: t`Tag already in use`,
            message: t`This tag is linked to another unit. Use a different tag.`,
            color: 'red'
          });
          setUid('');
          return;
        }
      } catch {
        // lookup failed — fall through and let submit-time validation catch it
      }

      setUid(scanned);
      playSound(cfg.sound_enabled, 'success');
      notifications.show({ title: t`Tag scanned`, message: scanned, color: 'green' });
    } catch {
      notifications.show({
        title: t`Scan failed`,
        message: t`Could not read a tag. Try again.`,
        color: 'red'
      });
    } finally {
      setScanning(false);
    }
  }

  async function handleSubmit() {
    if (!hasPart || submitting) return;

    // A container must be chosen for the unit.
    if (!container) {
      notifications.show({
        title: t`Container required`,
        message: t`Choose the container type for this unit.`,
        color: 'red'
      });
      return;
    }

    // Ampoules (whole units) must have a unit number (serial).
    if (behaviour === 'whole' && !serial.trim()) {
      notifications.show({
        title: t`Unit number required`,
        message: t`Ampoules need a unit number (serial). Please enter one.`,
        color: 'red'
      });
      return;
    }

    // Warn if the expiry date has already passed (may be legitimate for old
    // stock, so confirm rather than block).
    if (expiry.trim()) {
      const today = new Date().toISOString().slice(0, 10);
      if (expiry.trim() < today) {
        const ok = window.confirm(
          t`This expiry date has already passed. Add this unit anyway?`
        );
        if (!ok) return;
      }
    }

    setSubmitting(true);
    try {
      const body: Record<string, any> = {
        part_id: Number(partId),
        container_type: container,
        batch: batch.trim(),
        expiry_date: expiry.trim() || null,
        received_date: received.trim() || null
      };
      if (behaviour === 'whole') {
        // Ampoule: one physical unit identified by serial, quantity forced to 1.
        body.serial = serial.trim();
        body.quantity = 1;
      } else {
        // Poche / flacon: quantity-tracked (mL / mg), no serial.
        body.serial = '';
        body.quantity =
          typeof quantity === 'string' ? parseFloat(quantity) || 0 : quantity;
      }
      if (uid.trim()) body.uid = uid.trim();

      const res = await context.api.post('/plugin/nfc/create-item/', body);
      const data = res.data;
      notifications.show({
        title: t`Unit created`,
        message: data.part_name ?? '',
        color: 'green'
      });
      // Reset unit fields, keep the part selected for quick repeat entry.
      setBatch('');
      setSerial('');
      setExpiry('');
      setReceived('');
      setUid('');
      setQuantity(1);
    } catch (err: any) {
      notifications.show({
        title: t`Creation failed`,
        message: err?.response?.data?.error ?? t`Could not create the unit.`,
        color: 'red'
      });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Stack gap='sm'>
      <Text fw={600}>{t`Create unit`}</Text>

      {/* Part selector first — the rest is disabled until a part is chosen */}
      <Select
        label={t`Product (part)`}
        placeholder={t`Search a product...`}
        searchable
        value={partId}
        onChange={(v) => {
          if (v === CREATE_NEW) {
            if (onRequestCreatePart) onRequestCreatePart();
            return;
          }
          setPartId(v);
        }}
        data={[
          { value: CREATE_NEW, label: t`➕ Create new part` },
          ...parts
        ]}
        required
      />

      {!hasPart && (
        <Text size='xs' c='dimmed'>
          {t`Choose a product first to enable the unit fields.`}
        </Text>
      )}

      {hasPart && (
        <Select
          label={t`Container type`}
          description={
            partForm === 'Poudre'
              ? t`Powder → Flacon poudre (mg)`
              : partForm === 'Solution'
                ? t`Solution → Ampoule (whole) or Poche (mL)`
                : undefined
          }
          placeholder={t`Choose container`}
          data={containerOptions}
          value={container}
          onChange={setContainer}
          disabled={containerOptions.length === 1}
          required
        />
      )}

      {hasPart && !container && (
        <Text size='xs' c='dimmed'>
          {t`Choose a container to continue.`}
        </Text>
      )}

      <TextInput
        label={t`Lot number`}
        value={batch}
        onChange={(e) => setBatch(e.currentTarget.value)}
        disabled={!ready}
      />
      {behaviour === 'whole' ? (
        <>
          <TextInput
            label={t`Unit number (serial)`}
            value={serial}
            onChange={(e) => setSerial(e.currentTarget.value)}
            disabled={!ready}
            required
          />
          <Text size='xs' c='dimmed'>
            {t`Whole unit (ampoule) → quantity is 1.`}
          </Text>
        </>
      ) : (
        <NumberInput
          label={unitLabel ? `${t`Quantity`} (${unitLabel})` : t`Quantity`}
          description={unitLabel ? `${t`Remaining amount in`} ${unitLabel}` : undefined}
          min={0}
          value={quantity}
          onChange={setQuantity}
          disabled={!ready}
        />
      )}

      <TextInput
        type='date'
        label={t`Expiry date`}
        value={expiry}
        onChange={(e) => setExpiry(e.currentTarget.value)}
        disabled={!ready}
      />
      <TextInput
        type='date'
        label={t`Reception date`}
        value={received}
        onChange={(e) => setReceived(e.currentTarget.value)}
        disabled={!ready}
      />

      {/* Optional tag — scan only */}
      <Group align='end' gap='xs'>
        <TextInput
          style={{ flex: 1 }}
          label={t`NFC tag (optional)`}
          placeholder={t`Scan to fill`}
          value={uid}
          readOnly
          tabIndex={-1}
          disabled={!ready}
          styles={{ input: { pointerEvents: 'none', cursor: 'default' } }}
        />
        <ReaderDot connected={readerConnected} />
        <Button
          variant='light'
          leftSection={scanning ? <Loader size={14} /> : <IconWifi size={16} />}
          loading={scanning}
          disabled={!ready || !readerConnected}
          onClick={handleScan}
        >
          {t`Scan`}
        </Button>
      </Group>

      <Button
        mt='xs'
        leftSection={<IconCheck size={16} />}
        disabled={!ready || (behaviour === 'whole' && !serial.trim())}
        loading={submitting}
        onClick={handleSubmit}
      >
        {t`Add unit`}
      </Button>
    </Stack>
  );
}

// ---------------------------------------------------------------------------
// CREATE TABS — container holding both forms with cross-tab handoff.
//   - Product created -> asks "add a unit?" -> switches to Item tab, part preset
//   - Item tab "create new part" -> switches to Product tab (no data carried)
// ---------------------------------------------------------------------------

export function CreateTabs({ context }: { context: InvenTreePluginContext }) {
  const [tab, setTab] = useState<string | null>('part');
  const [presetPartId, setPresetPartId] = useState<number | null>(null);

  // After a product is created, ask whether to add a unit for it.
  const [askUnitFor, setAskUnitFor] = useState<{ id: number; name: string } | null>(null);

  return (
    <>
      <Modal
        opened={!!askUnitFor}
        onClose={() => setAskUnitFor(null)}
        title={t`Product created`}
        centered
        size='sm'
      >
        <Stack gap='sm'>
          <Text size='sm'>
            {t`Add a physical unit for`} <strong>{askUnitFor?.name}</strong>?
          </Text>
          <Group justify='flex-end' gap='xs'>
            <Button variant='default' size='xs' onClick={() => setAskUnitFor(null)}>
              {t`No, done`}
            </Button>
            <Button
              size='xs'
              color='teal'
              onClick={() => {
                if (askUnitFor) {
                  setPresetPartId(askUnitFor.id);
                  setTab('item');
                }
                setAskUnitFor(null);
              }}
            >
              {t`Yes, add a unit`}
            </Button>
          </Group>
        </Stack>
      </Modal>

      <Stack gap='sm'>
        <SegmentedControl
          fullWidth
          size='md'
          value={tab ?? 'part'}
          onChange={setTab}
          data={[
            { value: 'part', label: t`Product` },
            { value: 'item', label: t`Unit` }
          ]}
        />

        {tab === 'part' ? (
          <CreatePartForm
            context={context}
            onCreated={(id, name) => setAskUnitFor({ id, name })}
          />
        ) : (
          <CreateItemForm
            context={context}
            presetPartId={presetPartId}
            onRequestCreatePart={() => setTab('part')}
          />
        )}
      </Stack>
    </>
  );
}
