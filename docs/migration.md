# Install the NFC Plugin on the Existing InvenTree Server

Your InvenTree server is already working. Run these commands on the Debian server.

Repository: `https://github.com/Wassim-dxdydz/InvenTree`
Plugin folder in repository: `NFC/`

---

## 1. Go to your InvenTree Docker folder

This is the folder that contains `docker-compose.yml` and `.env`.

```bash
cd /opt/inventree
```

Check that you are in the right place:

```bash
ls -la
```

You must see:

```text
docker-compose.yml
.env
```

> If you used another folder when you installed InvenTree, use that folder instead of `/opt/inventree`.

---

## 2. Find the persistent InvenTree data folder

```bash
grep INVENTREE_EXT_VOLUME .env
```

Example output:

```text
INVENTREE_EXT_VOLUME=/opt/inventree/data
```

In the next commands, replace `/opt/inventree/data` with the path shown by your command if it is different.

---

## 3. Add your plugin to `plugins.txt`

Open the plugin list:

```bash
nano /opt/inventree/data/plugins.txt
```

Add this line at the bottom:

```text
git+https://github.com/Wassim-dxdydz/InvenTree.git#subdirectory=NFC
```

Save in nano:

```text
Ctrl+O  → Enter  → Ctrl+X
```

Check the result:

```bash
cat /opt/inventree/data/plugins.txt
```

You must see:

```text
git+https://github.com/Wassim-dxdydz/InvenTree.git#subdirectory=NFC
```

---

## 4. Install the plugin into the Docker containers

Run from `/opt/inventree`:

```bash
docker compose run --rm inventree-server invoke update
```

Wait until it finishes. This reads `plugins.txt` and installs the plugin from GitHub.

If it succeeds, continue.

---

## 5. Restart InvenTree

```bash
docker compose restart inventree-server inventree-worker
```

---

## 6. Activate the plugin in the browser

1. Open your InvenTree website.
2. Log in as an administrator.
3. Go to **Settings → Plugins → Plugin Settings**.
4. Make sure plugins are enabled.
5. Find your NFC plugin.
6. Activate it.

Then refresh the page and open any Part. Your NFC panel should appear.

---

## 7. If the plugin does not appear

Run these commands:

```bash
cd /opt/inventree
docker compose logs inventree-server | grep -i nfc
docker compose logs inventree-worker | grep -i nfc
```

Also check that InvenTree installed the package:

```bash
docker compose exec inventree-server pip list | grep -i nfc
```

---

## 8. NFC reader agent — separate workstation step

The plugin runs on the company server. The USB NFC reader does not.

On each employee Linux computer that has the USB NFC reader connected:

```bash
git clone https://github.com/Wassim-dxdydz/InvenTree.git
cd InvenTree/NFC/agent
```

Then run your agent installation and start commands:

```bash
bash install.sh
python agent.py
```

The browser on that same computer communicates with its local agent at `127.0.0.1` to read NFC tags.

---

## Updating the plugin later

After you push a new plugin version to GitHub, run on the server:

```bash
cd /opt/inventree
docker compose run --rm inventree-server invoke update
docker compose restart inventree-server inventree-worker
```

Do not run `pip install` manually inside a Docker container; container-only changes disappear when the container is recreated. `plugins.txt` is the persistent installation source. InvenTree supports Docker plugin installation through `plugins.txt` in the external data directory. [web:43][web:42]
