# Usage

This document explains how to use the NFC plugin after it is installed and the
agent is running.

## Overview

The plugin lets you manage individual physical units of stock with NFC tags. You
can:

- Scan a tag to identify the unit and its product.
- Create new products and units (including several units at once).
- Remove stock from a unit, or mark a whole unit as used.
- Link and unlink tags.
- Review the full history of a unit (who did what, when, and how much).

Each unit is one physical container. Three container types are supported:

- **Ampoule** — a whole unit, consumed all at once. Marking it used sends it to
  zero (out of stock).
- **Poche** — a bag/septum container, tracked in millilitres (mL); you remove
  partial amounts.
- **Flacon poudre** — a resealable powder vial, tracked in milligrams (mg); you
  remove partial amounts.

The plugin talks to a local NFC agent on the workstation that has the USB
reader. Each workstation reaches its own agent.

## Where the panel appears

The NFC panel is available on Part, Stock Item, Stock Location and Part Category
pages, plus a scan widget on the dashboard and a Spotlight action. Open the
relevant page and expand the NFC panel.

## Reader status

A coloured dot shows the reader state:

- **Green** — the agent is reachable and a reader is connected.
- **Yellow** — the agent is being checked, or a scan is in progress.
- **Red** — the agent is unreachable, or no reader is connected.

If it stays red, check that the reader is plugged in, the agent is running, and
that this workstation's agent URL is correct (see *Agent settings* below).

## Scan a tag

1. Confirm the reader status is green.
2. Click **Scan NFC Tag**.
3. Place the tag on the reader.

If the tag is linked to a unit, the panel shows three zones:

- The **product** (its full name, clickable to open the part).
- The **scanned unit** — lot, expiry, reception date, location and remaining
  quantity, with the actions available for it.
- The **other units** of the same product, shown as compact cards you can click
  to open.

If the tag is unknown, the panel says so; you can then create a unit for it.

## Create products and units

Expand the **Create** section.

### Create a product

Fill in the product fields (molecule, laboratory, dosage, form). The product
name is assembled automatically. A product describes a medication; the physical
units come next.

### Create one or more units

1. Choose the product.
2. Choose the container type (filtered to what the product's form allows:
   Solution → Ampoule or Poche; Poudre → Flacon poudre).
3. Choose a **location** (required). Structural locations — folders that can't
   hold stock — are not shown.
4. Fill in the lot, quantity, expiry and reception dates.
   - Dates are **month + year**. You can type `mm-yyyy`, `mm/yyyy`, `yyyy-mm`
     or `yyyy/mm`. The month must be 01–12.
5. **Add tags**: scan one or more tags. Each scanned tag appears as a chip. A
   tag that is already in the list or already linked to another unit is refused
   with a notice, so only valid tags are added.
6. Submit. **One identical unit is created per tag** (same product, container,
   location, lot, dates and quantity). If you add no tags, a single untagged
   unit is created.

## Adjust stock

On a scanned unit:

### Quantity-tracked units (Poche, Flacon poudre)

- Enter an amount to remove and click **Remove**.
- You cannot remove more than remains. If you try, the amount is not clamped
  silently — you get a clear message telling you the available amount and to
  choose a lower value.
- You are asked to confirm; then a notification shows how much was removed and
  what remains.
- Adding stock back is intentionally not offered — new stock is a new unit.

### Whole units (Ampoule)

- Click **Mark as used** and confirm.
- The unit goes to zero immediately and becomes out of stock; the button
  disappears.

## Out of stock

When any unit reaches zero:

- The record is **kept** (never auto-deleted) and marked out of stock.
- The tag **stays linked** until someone unlinks it manually.
- The panel shows an "Out of stock" badge with the used date instead of the
  action buttons. Re-scanning the tag shows the out-of-stock state.

## Link and unlink tags

On a Stock Item page, expand the NFC panel's tag section:

- If the unit has no tag, scan one to **link** it.
- If it has a tag, its UID is shown with an **Unlink** button.

Any logged-in user can link and unlink — accountability comes from the history,
not from restricting the action. A tag can only be linked to one active unit,
and a unit to one active tag; conflicts are rejected with a clear message.

## History

Click **Show history** on a scanned unit to see its timeline, newest first:

- **Unit created** — who created it, when, and the initial quantity.
- **Stock change** — each removal or "mark as used": who, when, the change and
  the resulting quantity.
- **Tag linked / unlinked** — deliberate link/unlink actions with the user and
  time.

History records events from the moment the recording code is live, so newly
created units and new actions are fully tracked.

## Agent settings (this workstation)

Because each workstation can differ, the agent URL and scan timeout are
configured **per machine**, stored in that browser. Open the **Agent settings
(this workstation)** section in the panel (available to all users) or the plugin
settings page:

- Set this workstation's agent URL (default `http://127.0.0.1:8765`) and scan
  timeout.
- **Test connection** checks the agent and reader.
- **Reset** returns to the built-in default.

Leaving the fields empty uses the default, so most workstations need no changes.

## Typical workflow

1. Start the agent on the workstation.
2. Open InvenTree; confirm the reader dot is green.
3. Scan a tag to find a unit, or create new units for new tags.
4. Remove stock or mark units used as they are consumed.
5. Link or unlink tags as needed; review history for accountability.

## Tips

- Keep the reader connected before opening InvenTree; refresh if the agent was
  started after the page loaded.
- If the status never turns green, check this workstation's agent settings and
  the troubleshooting guide.
- Dates only need month and year; any of the four formats is accepted.