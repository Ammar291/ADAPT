# Hosted live demo

Runs the full stack on one cloud VM with real OpenAI behind every AI capability (journey
planning, assistant, document reading, research, embeddings, voice). No deterministic demo
adapters and no frontend mocks. Visitors get a public HTTPS link and one-click demo sign-in.

| Setting | Value | Why |
|---|---|---|
| `ADAPTER_LLM/EMBEDDINGS/OCR/VOICE/WEB_SEARCH` | `live` | Startup fails without a key, never a silent fallback to demo adapters |
| `VITE_DATA_MODE` | `live` | The frontend never shows mock data |
| `ADAPT_ENV` | `development` | Production refuses demo sign-in, and demo sign-in is the only sign-in |
| `ADAPTER_ACTIONS` | `auto` (preview) | Government actions show previews; nothing is ever filed |
| HTTPS | Caddy + Let's Encrypt | The microphone and secure cookies need it |

## 1. Create a VM

Any provider works. DigitalOcean is fastest to set up, and it bills hourly, so destroy the
VM after the demo. Choose:

- **Ubuntu 24.04**, **2 vCPU / 4 GB RAM** (Basic droplet, about $0.04 an hour)
- the region closest to your audience
- **SSH key** authentication (paste `~/.ssh/id_ed25519.pub`)

On AWS, GCP or Azure, also open inbound ports **80** and **443** in the firewall or
security group.

## 2. Protect the key

Anyone with the link can sign in and spend your OpenAI credits. Create a dedicated
**project key** at platform.openai.com, set a **monthly budget** on that project, and
revoke the key after the demo.

## 3. Deploy

```bash
ssh root@<VM_IP>
git clone https://github.com/Ammar291/ADAPT.git /opt/adapt
bash /opt/adapt/infra/demo/setup-server.sh     # paste the key when prompted (hidden)
```

The first build takes about 5 to 10 minutes. The script prints the URL
(`https://<ip-with-dashes>.sslip.io`, no domain purchase needed), checks that every AI
capability reports `live`, and confirms that HTTPS works. To use your own domain, point
its A record at the VM and run with `ADAPT_DOMAIN=demo.example.com`.

The key lives only in `/opt/adapt/.env` on the VM (mode 600). It is never in git or the
frontend bundle. Voice sessions use short-lived keys minted by the backend.

## Operate

| Task | Command (in `/opt/adapt`) |
|---|---|
| Deploy the latest `main` | `bash infra/demo/setup-server.sh` |
| Follow the logs | `docker compose -f docker-compose.yml -f docker-compose.demo.yml logs -f backend worker` |
| Rotate the key | `OPENAI_API_KEY=sk-... bash infra/demo/setup-server.sh` |
| Stop | `docker compose -f docker-compose.yml -f docker-compose.demo.yml down` |

For an offline stage fallback with no network or key, see [DEMO_RUNBOOK.md](../DEMO_RUNBOOK.md).
