import type { InvenTreePluginContext } from '@inventreedb/ui';
import { t } from '@lingui/core/macro';
import {
  ActionIcon,
  Alert,
  Autocomplete,
  Box,
  Button,
  Group,
  Loader,
  Modal,
  NumberInput,
  SegmentedControl,
  Select,
  Stack,
  Text,
  Textarea,
  TextInput
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import {
  IconCheck,
  IconPlayerStop,
  IconWifi,
  IconX
} from '@tabler/icons-react';
import { useEffect, useState } from 'react';
import { getEffectiveConfig } from './agentConfig';
import {
  createItem,
  createProduct,
  fetchLocations,
  fetchManufacturers,
  fetchPartInfo,
  fetchParts,
  findByTag
} from './api';
import { useAgentScan, useReaderStatus } from './hooks';
import { playSound } from './sound';
import type { PartOption } from './types';

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

/** Pharmaceutical natures offered by the product form (stored as-is). */
const NATURE_ACTIVE_SUBSTANCE = 'Principe actif';
const NATURES = ['Médicament formulé', NATURE_ACTIVE_SUBSTANCE];

/** Maximum length of the excipients text (InvenTree parameter limit). */
const EXCIPIENTS_MAX_LENGTH = 500;

/** Maximum number of units created in one go. */
const MAX_UNITS = 100;

/**
 * Extract a human-readable message from any DRF/InvenTree error payload:
 * a plain string, { error: "..." }, or { field: ["msg", ...] }.
 */
function extractError(err: any, fallback: string): string {
  const data = err?.response?.data;
  if (!data) return fallback;
  if (typeof data === 'string') return data;
  if (typeof data.error === 'string') return data.error;
  const parts: string[] = [];
  for (const key of Object.keys(data)) {
    const val = data[key];
    if (Array.isArray(val)) parts.push(val.join(' '));
    else if (typeof val === 'string') parts.push(val);
  }
  return parts.length ? parts.join(' — ') : fallback;
}

/**
 * Parse a month/year string in any of: mm-yyyy, mm/yyyy, yyyy-mm, yyyy/mm.
 * Returns { ym: 'YYYY-MM' } on success, { error } when invalid, {} when empty.
 * Month must be between 01 and 12.
 */
function parseMonthYear(input: string): { ym?: string; error?: string } {
  const s = (input || '').trim();
  if (!s) return {};

  const parts = s.split(/[-/]/);
  if (parts.length !== 2 || parts.some((p) => !/^\d+$/.test(p))) {
    return { error: 'Use mm-yyyy, mm/yyyy, yyyy-mm or yyyy/mm.' };
  }

  let year: number;
  let month: number;
  if (parts[0].length === 4) {
    year = Number(parts[0]);
    month = Number(parts[1]);
  } else if (parts[1].length === 4) {
    month = Number(parts[0]);
    year = Number(parts[1]);
  } else {
    return { error: 'Year must have 4 digits (e.g. 2027).' };
  }

  if (month < 1 || month > 12)
    return { error: 'Month must be between 01 and 12.' };
  if (year < 2000 || year > 2100)
    return { error: 'Year must be between 2000 and 2100.' };
  return { ym: `${year}-${String(month).padStart(2, '0')}` };
}

/** Container types allowed for a product form (all of them when the form is unknown). */
function containersForForm(form: string | null): string[] {
  if (form === 'Poudre') return ['Flacon poudre'];
  if (form === 'Solution')
    return ['Ampoule', 'Poche', 'Flacon Solution', 'Seringue'];
  return ['Ampoule', 'Poche', 'Flacon Solution', 'Seringue', 'Flacon poudre'];
}

/** Unit of measure of a container managed by quantity, or null for whole units. */
function containerUnit(container: string | null): string | null {
  if (container === 'Poche') return 'mL';
  if (
    container === 'Flacon poudre' ||
    container === 'Flacon Solution' ||
    container === 'Seringue'
  )
    return 'mg';
  return null;
}

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

// ---------------------------------------------------------------------------
// CREATE PART form
// ---------------------------------------------------------------------------

/**
 * Product (part) creation form: drug name, molecule, mass/concentration, form,
 * manufacturer, nature and excipients (none for an active substance). The
 * product name is built automatically from the identity fields.
 */
export function CreatePartForm({
  context,
  onCreated
}: {
  context: InvenTreePluginContext;
  onCreated?: (partId: number, partName: string) => void;
}) {
  const [drugName, setDrugName] = useState('');
  const [molecule, setMolecule] = useState('');
  const [dosage, setDosage] = useState('');
  const [form, setForm] = useState<string | null>('Solution');
  const [nature, setNature] = useState<string | null>(null);
  const [manufacturer, setManufacturer] = useState('');
  const [excipients, setExcipients] = useState('');
  const [manufacturers, setManufacturers] = useState<string[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);

  useEffect(() => {
    let active = true;
    fetchManufacturers(context.api)
      .then((names) => active && setManufacturers(names))
      .catch(() => active && setManufacturers([]));
    return () => {
      active = false;
    };
  }, [context.api]);

  const typedManufacturer = manufacturer.trim();
  const knownManufacturer = manufacturers.find(
    (name) => name.toLowerCase() === typedManufacturer.toLowerCase()
  );
  const manufacturerName = knownManufacturer ?? typedManufacturer;
  const allowsExcipients = nature !== NATURE_ACTIVE_SUBSTANCE;
  const excipientsValue = allowsExcipients ? excipients.trim() : '';

  const previewName = [drugName, molecule, manufacturerName, dosage, form]
    .map((s) => (s || '').trim())
    .filter(Boolean)
    .join(' ');

  const canSubmit =
    !!molecule.trim() &&
    !!dosage.trim() &&
    (form === 'Solution' || form === 'Poudre');

  function resetFields() {
    setDrugName('');
    setMolecule('');
    setDosage('');
    setNature(null);
    setManufacturer('');
    setExcipients('');
    setForm('Solution');
  }

  async function doCreate() {
    setConfirmOpen(false);
    if (!canSubmit || submitting) return;
    setSubmitting(true);
    try {
      const data = await createProduct(context.api, {
        drug_name: drugName.trim(),
        molecule: molecule.trim(),
        dosage: dosage.trim(),
        form,
        nature: nature ?? '',
        manufacturer: manufacturer.trim(),
        excipients: excipientsValue,
        add_unit: false
      });
      notifications.show({
        title: data.reused_existing_part
          ? t`Product already exists`
          : t`Product created`,
        message: data.reused_existing_part
          ? t`This product already exists — no new product was created.`
          : data.part_name,
        color: data.reused_existing_part ? 'yellow' : 'green'
      });
      resetFields();
      if (typedManufacturer && !knownManufacturer) {
        setManufacturers((prev) => [...prev, typedManufacturer].sort());
      }
      if (!data.reused_existing_part && onCreated) {
        onCreated(data.part_id, data.part_name);
      }
    } catch (err: any) {
      notifications.show({
        title: t`Creation failed`,
        message: extractError(err, t`Could not create the product.`),
        color: 'red'
      });
    } finally {
      setSubmitting(false);
    }
  }

  const details = [
    `${t`Molecule:`} ${molecule}`,
    `${t`Mass / concentration:`} ${dosage}`,
    `${t`Form:`} ${form}`,
    manufacturerName ? `${t`Manufacturer:`} ${manufacturerName}` : '',
    nature ? `${t`Nature:`} ${nature}` : ''
  ]
    .filter(Boolean)
    .join(' · ');

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
            <Text size='sm' fw={600}>
              {previewName}
            </Text>
            <Text size='xs' c='dimmed'>
              {details}
            </Text>
            {excipientsValue && (
              <Text size='xs' c='dimmed'>
                {t`Excipients:`} {excipientsValue}
              </Text>
            )}
          </Alert>
          <Group justify='flex-end' gap='xs'>
            <Button
              variant='default'
              size='xs'
              onClick={() => setConfirmOpen(false)}
            >
              {t`Cancel`}
            </Button>
            <Button
              size='xs'
              color='teal'
              loading={submitting}
              onClick={doCreate}
            >
              {t`Confirm`}
            </Button>
          </Group>
        </Stack>
      </Modal>

      <Text fw={600}>{t`Create product`}</Text>

      <TextInput
        label={t`Drug name`}
        placeholder='Doliprane'
        value={drugName}
        onChange={(e) => setDrugName(e.currentTarget.value)}
      />
      <TextInput
        label={t`Molecule (DCI)`}
        placeholder='Paracétamol'
        value={molecule}
        onChange={(e) => setMolecule(e.currentTarget.value)}
        required
      />
      <TextInput
        label={t`Mass / concentration`}
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
      <Select
        label={t`Nature`}
        placeholder={t`Choose a nature`}
        data={NATURES}
        value={nature}
        onChange={(value) => {
          setNature(value);
          if (value === NATURE_ACTIVE_SUBSTANCE) setExcipients('');
        }}
        clearable
      />
      <Autocomplete
        label={t`Manufacturer`}
        description={
          typedManufacturer && !knownManufacturer
            ? t`New manufacturer: it will be created.`
            : undefined
        }
        placeholder='Fresenius Kabi'
        data={manufacturers}
        value={manufacturer}
        onChange={setManufacturer}
      />
      {allowsExcipients && (
        <Textarea
          label={t`Excipients`}
          placeholder='Mannitol, eau pour préparations injectables'
          autosize
          minRows={2}
          maxLength={EXCIPIENTS_MAX_LENGTH}
          description={`${excipients.length}/${EXCIPIENTS_MAX_LENGTH}`}
          value={excipients}
          onChange={(e) => setExcipients(e.currentTarget.value)}
        />
      )}

      {previewName && (
        <Alert color='blue' variant='light' p='xs'>
          <Text size='xs' c='dimmed'>{t`Product name will be:`}</Text>
          <Text size='sm' fw={600}>
            {previewName}
          </Text>
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

/**
 * Unit (stock item) creation form: one or more identical units of a product,
 * with a storage location (picked or created), a contenance for bag/vial
 * containers, month/year dates and an optional NFC tag per unit.
 */
export function CreateItemForm({
  context,
  presetPartId,
  onRequestCreatePart
}: {
  context: InvenTreePluginContext;
  presetPartId?: number | null;
  onRequestCreatePart?: () => void;
}) {
  const [parts, setParts] = useState<PartOption[]>([]);
  const [partId, setPartId] = useState<string | null>(
    presetPartId ? String(presetPartId) : null
  );
  const [locations, setLocations] = useState<PartOption[]>([]);
  const [locationText, setLocationText] = useState('');
  const [batch, setBatch] = useState('');
  const [expiry, setExpiry] = useState('');
  const [received, setReceived] = useState('');
  const [quantity, setQuantity] = useState<number | string>(1);
  const [count, setCount] = useState<number | string>(1);
  const [tagSlots, setTagSlots] = useState<string[]>(['']);
  const [scanningSlot, setScanningSlot] = useState<number | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const [partForm, setPartForm] = useState<string | null>(null);
  const [container, setContainer] = useState<string | null>(null);

  const scan = useAgentScan();
  const readerConnected = useReaderStatus(context);

  const containerOptions = containersForForm(partForm);
  const unitLabel = containerUnit(container);
  const unitCount = Math.min(
    MAX_UNITS,
    Math.max(
      1,
      Math.floor(typeof count === 'string' ? parseInt(count, 10) || 1 : count)
    )
  );

  const matchedLocation = locations.find(
    (l) => l.label === locationText.trim()
  );
  const isNewLocation = !!locationText.trim() && !matchedLocation;

  useEffect(() => {
    let active = true;
    fetchParts(context.api)
      .then((opts) => active && setParts(opts))
      .catch(() => active && setParts([]));
    return () => {
      active = false;
    };
  }, [context.api]);

  useEffect(() => {
    let active = true;
    fetchLocations(context.api)
      .then((opts) => active && setLocations(opts))
      .catch(() => active && setLocations([]));
    return () => {
      active = false;
    };
  }, [context.api]);

  useEffect(() => {
    if (presetPartId) setPartId(String(presetPartId));
  }, [presetPartId]);

  useEffect(() => {
    setTagSlots((prev) =>
      Array.from({ length: unitCount }, (_, i) => prev[i] ?? '')
    );
  }, [unitCount]);

  const CREATE_NEW = '__create_new__';
  const hasPart = !!partId && partId !== CREATE_NEW;
  const showFields = hasPart && !!container;
  const ready = showFields && !!locationText.trim();

  useEffect(() => {
    if (!hasPart) {
      setPartForm(null);
      setContainer(null);
      return;
    }
    let active = true;
    fetchPartInfo(context.api, partId)
      .then((data) => {
        if (!active) return;
        const f = data?.form ?? null;
        setPartForm(f);
        const options = containersForForm(f);
        setContainer(options.length === 1 ? options[0] : null);
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

  async function scanSlot(index: number) {
    if (scan.scanning) return;
    setScanningSlot(index);
    try {
      const cfg = await getEffectiveConfig(context.api);
      playSound(cfg.sound_enabled, 'click');
      const scanned = await scan.start(
        cfg.agent_base_url,
        cfg.scan_timeout_seconds
      );
      if (scanned === null) return;

      if (tagSlots.some((u, i) => i !== index && u === scanned)) {
        playSound(cfg.sound_enabled, 'error');
        notifications.show({
          title: t`Already added`,
          message: t`That tag is already used by another unit of this form.`,
          color: 'orange'
        });
        return;
      }
      try {
        const check = await findByTag(context.api, scanned);
        if (check?.found) {
          playSound(cfg.sound_enabled, 'error');
          notifications.show({
            title: t`Tag already in use`,
            message: t`This tag is linked to another unit.`,
            color: 'red'
          });
          return;
        }
      } catch {
        /* lookup failed — the server validates again on creation */
      }

      setTagSlots((prev) => prev.map((u, i) => (i === index ? scanned : u)));
      playSound(cfg.sound_enabled, 'success');
    } catch (err: any) {
      notifications.show({
        title: t`Scan failed`,
        message:
          err?.code === 'timeout' || err?.code === 'client_timeout'
            ? t`No tag detected before timeout.`
            : t`Could not read a tag. Try again.`,
        color: 'red'
      });
    } finally {
      setScanningSlot(null);
    }
  }

  function clearSlot(index: number) {
    setTagSlots((prev) => prev.map((u, i) => (i === index ? '' : u)));
  }

  async function handleSubmit() {
    if (!ready || submitting || !container) return;

    const expiryParsed = parseMonthYear(expiry);
    if (expiryParsed.error) {
      notifications.show({
        title: t`Invalid expiry date`,
        message: expiryParsed.error,
        color: 'red'
      });
      return;
    }
    const receivedParsed = parseMonthYear(received);
    if (receivedParsed.error) {
      notifications.show({
        title: t`Invalid reception date`,
        message: receivedParsed.error,
        color: 'red'
      });
      return;
    }
    if (
      expiryParsed.ym &&
      expiryParsed.ym < new Date().toISOString().slice(0, 7)
    ) {
      if (
        !window.confirm(
          t`This expiry date has already passed. Continue anyway?`
        )
      ) {
        return;
      }
    }

    setSubmitting(true);
    try {
      const body: Record<string, any> = {
        part_id: Number(partId),
        container_type: container,
        batch: batch.trim(),
        expiry_date: expiryParsed.ym ?? null,
        received_date: receivedParsed.ym ?? null,
        quantity:
          typeof quantity === 'string' ? parseFloat(quantity) || 0 : quantity,
        count: unitCount,
        uids: tagSlots
      };
      if (matchedLocation) body.location_id = Number(matchedLocation.value);
      else body.location_name = locationText.trim();

      const data = await createItem(context.api, body);
      const n = data?.created_count ?? 0;
      notifications.show({
        title: n > 1 ? t`Units created` : t`Unit created`,
        message: `${data.part_name ?? ''} — ${n} · ${data.location_name ?? ''}`,
        color: 'green'
      });
      if (isNewLocation) {
        fetchLocations(context.api)
          .then(setLocations)
          .catch(() => undefined);
      }
      setBatch('');
      setExpiry('');
      setReceived('');
      setQuantity(1);
      setCount(1);
      setTagSlots(['']);
    } catch (err: any) {
      notifications.show({
        title: t`Creation failed`,
        message: extractError(err, t`Could not create the unit(s).`),
        color: 'red'
      });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Stack gap='sm'>
      <Text fw={600}>{t`Create unit`}</Text>

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
        data={[{ value: CREATE_NEW, label: t`➕ Create new part` }, ...parts]}
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
                ? t`Solution → Ampoule (whole), Poche (mL), Flacon Solution or Seringue (mg)`
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

      {showFields && (
        <>
          <Autocomplete
            label={t`Storage location`}
            placeholder={t`Choose or type a new location`}
            description={
              isNewLocation
                ? `${t`New location:`} « ${locationText.trim()} » ${t`will be created.`}`
                : undefined
            }
            data={locations.map((l) => l.label)}
            value={locationText}
            onChange={setLocationText}
            required
          />
          <TextInput
            label={t`Lot number`}
            value={batch}
            onChange={(e) => setBatch(e.currentTarget.value)}
          />
          <NumberInput
            label={t`Number of units to add`}
            min={1}
            max={MAX_UNITS}
            allowDecimal={false}
            value={count}
            onChange={setCount}
            required
          />
          {unitLabel ? (
            <NumberInput
              label={`${t`Quantity`} (${unitLabel})`}
              description={t`Contenance of each unit.`}
              min={0}
              value={quantity}
              onChange={setQuantity}
              required
            />
          ) : (
            <Text
              size='xs'
              c='dimmed'
            >{t`Whole unit (ampoule) → quantity is 1.`}</Text>
          )}
          <TextInput
            label={t`Expiry`}
            description={t`Month/year (mm-yyyy): valid until the end of the month.`}
            placeholder='mm-yyyy'
            value={expiry}
            onChange={(e) => setExpiry(e.currentTarget.value)}
          />
          <TextInput
            label={t`Reception`}
            description={t`Month/year (mm-yyyy).`}
            placeholder='mm-yyyy'
            value={received}
            onChange={(e) => setReceived(e.currentTarget.value)}
          />

          <div>
            <Group align='end' gap='xs'>
              <Text size='sm' style={{ flex: 1 }}>
                {t`NFC tags`} ({tagSlots.filter(Boolean).length}/{unitCount})
              </Text>
              <ReaderDot connected={readerConnected} />
            </Group>
            <Stack gap={4} mt={4}>
              {tagSlots.map((uid, index) => (
                <Group key={index} gap='xs' wrap='nowrap'>
                  <Text size='sm' w={70}>
                    {t`Unit`} {index + 1}
                  </Text>
                  <Text
                    size='sm'
                    c={uid ? undefined : 'dimmed'}
                    style={{ flex: 1 }}
                  >
                    {uid || t`No tag`}
                  </Text>
                  {scanningSlot === index ? (
                    <Button
                      size='xs'
                      color='red'
                      variant='light'
                      leftSection={<IconPlayerStop size={14} />}
                      onClick={scan.stop}
                    >
                      {t`Stop scan`}
                    </Button>
                  ) : (
                    <Button
                      size='xs'
                      variant='light'
                      leftSection={<IconWifi size={14} />}
                      disabled={!readerConnected || scanningSlot !== null}
                      onClick={() => scanSlot(index)}
                    >
                      {uid ? t`Rescan` : t`Scan`}
                    </Button>
                  )}
                  {uid && (
                    <ActionIcon
                      variant='subtle'
                      color='gray'
                      aria-label={t`Remove`}
                      onClick={() => clearSlot(index)}
                    >
                      <IconX size={14} />
                    </ActionIcon>
                  )}
                </Group>
              ))}
            </Stack>
            {scanningSlot !== null && (
              <Group gap='xs' mt={4}>
                <Loader size={14} />
                <Text size='xs' c='dimmed'>{t`Waiting for tag...`}</Text>
              </Group>
            )}
            <Text size='xs' c='dimmed' mt={4}>
              {t`Tags are optional: units without a tag can be linked later.`}
            </Text>
          </div>
        </>
      )}

      {hasPart && !container && (
        <Text size='xs' c='dimmed'>{t`Choose a container to continue.`}</Text>
      )}

      <Button
        mt='xs'
        leftSection={<IconCheck size={16} />}
        disabled={!ready}
        loading={submitting}
        onClick={handleSubmit}
      >
        {unitCount > 1 ? `${t`Create`} ${unitCount} ${t`units`}` : t`Add unit`}
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
  const [askUnitFor, setAskUnitFor] = useState<{
    id: number;
    name: string;
  } | null>(null);

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
            <Button
              variant='default'
              size='xs'
              onClick={() => setAskUnitFor(null)}
            >
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
