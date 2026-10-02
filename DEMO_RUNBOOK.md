# ADAPT: three-minute stage runbook

## Pre-demo setup

Use the synthetic stage presentation for the hackathon. It is visibly labeled **Recorded
LangGraph run**: the seed is built by the real compiled journey graph, real read-only
simulation graph, local PDF reader with MRZ validation, drafting templates and dated
research catalogue. The browser replays those results. Browser speech recognition and
speech synthesis provide the spoken opening. Do not describe this mode as a live cloud
agent execution, live VLM extraction, live web search or a government integration.

From the repository root:

```powershell
npm ci
npm run demo
```

Open **http://127.0.0.1:5181/demo/founder-arrival** in Chrome or Edge. Keep that terminal
running. `npm run demo` builds with `DEMO_MODE=true` and starts the production preview;
it does not edit `.env`. For rehearsal with hot reload, use `npm run demo:dev` on port
5180. Use the production build on stage. No backend, Docker or API key is required.

1. Connect power; disable OS notifications and sleep; select the intended speakers.
2. Use a clean browser profile, 100% zoom, preferably at least 1440 × 900 on desktop.
3. Click **Use scripted opening** once to check audio, then **Demo Reset**. Test microphone
   permission with **Speak the opening**. If the venue's recognition service is unavailable,
   keep the visible scripted-opening button as the fallback.
4. Visit all ten chapters once, wait for the service worker to install, then refresh. This
   warms fonts, the replay and the public specimen PDFs. Chrome/Edge can install ADAPT from
   the address-bar install icon or browser menu. On iOS use Share → Add to Home Screen.
5. Rehearse the sequence below. Click **Demo Reset** immediately before presenting.
6. Keep a second tab at `/demo/founder-arrival?scene=9` for a direct final-plan recovery.
   Progress is shared across tabs on this origin; do not reset the second tab mid-show.

Automated rehearsal after the demo build:

```powershell
npm test
npm run typecheck
npm run demo:build
npm run audit:demo
```

The browser audit requires Playwright and a Chromium browser. An existing installation can
be supplied with `ADAPT_PLAYWRIGHT_MODULE` (a file URL to Playwright's `index.mjs`) and
`ADAPT_BROWSER_EXECUTABLE` (absolute Chrome/Edge path). It produces
`frontend/qa-artifacts/demo-audit.json` and screenshots. It checks the hero sequence with
all API endpoints returning 503, voice permission/audio failure and reconnect, specimen
preview failure, reset, mobile, refresh, deep links, installability and offline navigation.

## Environment variables

| Variable | Stage value / purpose |
|---|---|
| `DEMO_MODE` | `true`; build-time presentation sandbox. `npm run demo`, `demo:dev` and `demo:build` set it automatically. |
| `VITE_DEMO_MODE` | Optional build-time alias when `DEMO_MODE` is unset. Do not enable for a real-user deployment. |
| `VITE_DATA_MODE` | Stage sandbox overrides this to mock and bypasses private API bootstrap. Outside demo mode: `auto`, `live` or `mock`. |
| `VITE_SHOW_DEV_BADGE` | Suppressed in the stage presentation. |
| `OPENAI_API_KEY` | Not required for stage mode; server-side only in live mode. Never use a `VITE_` key variable. |
| `ADAPT_PLAYWRIGHT_MODULE` | Optional existing Playwright module location for the browser audit. |
| `ADAPT_BROWSER_EXECUTABLE` | Optional browser executable for the browser audit. |

The explicit demo build has no private API access, real document picker or editable identity
fields. Only bundled synthetic documents are loaded. It caches app assets and public
specimens. APIs, private documents and uploads remain network-only. Stored progress is
an allowlist of chapter, completion flags, research/agent start times and the synthetic
appointment decision. Audio, transcripts, arbitrary text and credentials are never stored.
Browser dictation may use the browser vendor's recognition service; do not speak real data.

For Docker, set `DEMO_MODE=true` before `docker compose up --build`; the frontend build
argument carries it into the image. The existing Compose stack still starts its backend
dependencies. The native stage command above has fewer dependencies.

To return to the normal app, build with `DEMO_MODE=false` using `npm run build`. Environment
changes require rebuilding. Demo Reset is visible only in a demo build.

## Demo Reset

Click **Demo Reset** in the top bar. It cancels dictation, speech and pending specimen
requests, clears the reply and chapter URL, resets all synthetic completion/approval/branch
markers, and clears background start times. Initial state is chapter 1, no opening,
documents not loaded, agent/research not started, pending featured decision and family
arrival selected. The original seed bytes do not change. Refresh preserves this state.

Reset affects this presentation's progress, not live accounts or database records. Avoid
`docker compose down -v` as a stage reset.

## Exact click / voice sequence

Use **Continue** between chapters. Times are targets; the final 30 seconds are a buffer.

| Time | Click / voice | Show / say |
|---|---|---|
| 0:00–0:30 | **Speak the opening**. Say: “I'm an Indian technology founder moving to Abu Dhabi next month with my wife. I want to establish my company, find housing and understand the steps for settling my family.” | Spoken response and extracted intent. Company jurisdiction and opted-in faith are separate inputs in this fictional persona. |
| 0:30–0:45 | **Continue** → **Upload demo documents**. | Synthetic passport and marriage certificate, four extraction stages, fields and confidence. The bundled business profile supplies ADGM. These are recorded local-reader results; no live vision claim. |
| 0:45–0:55 | **Continue**. | User Digital Twin: founder, nationality, spouse, documents, company and goals. |
| 0:55–1:05 | **Continue**. | Governance Graph: services, eligibility rule, requirements, authority and official source. |
| 1:05–1:20 | **Continue** → **Start LangGraph journey**; allow about six seconds. | Animated actual node-event replay. **17 actions identified**, **2 blockers**, **1 approval required**. Scope is explicit: 22 total steps, two missing eligibility facts, one featured appointment approval; the full recorded plan also has a sponsor-file decision and additional document/dependency risks. |
| 1:20–1:35 | **Continue**. | One requirement: **User fact → Governance rule → Evidence → Next action**. Income remains unknown. Show the family dependency chain. |
| 1:35–1:50 | **Continue** → **Approve handoff**. | Draft sponsorship letter; example appointment slots; **Action prepared for official handoff**. State: “You finish on the official site. Nothing is booked or submitted.” Do not navigate away to the external portal during the three-minute presentation. |
| 1:50–2:10 | **Continue** → **Start background research**. Choose “How can we connect?” → **Ask ADAPT**, or speak a short community question with **Talk / reconnect**. | Research continues while the response plays. After nine seconds: Indian community, explicitly opted-in faith/community, professional network, cultural guidance and starter services. Cards retain source dates and make no current-contact claim. Show **Things you may not have considered.** |
| 2:10–2:30 | **Continue** → **Move alone first**. | Dashed branch: 11 steps move to the wife's later phase and 15 dependencies leave the first arrival. The base plan is preserved. |
| 2:30–3:00 | **Return to final plan**. | **YOUR ABU DHABI PLAN**: **Arrive · Settle · Connect · Build**, next actions, blockers, documents, handoff, community, cultural guide and research status. Finish here. |

## If voice fails

1. Click **Use scripted opening** immediately; the same intent and full response appear.
2. If audio is unavailable, read one sentence of the visible reply and click Continue.
3. During research, select the preset question and click **Ask ADAPT**. Its full response is
   visible even when speech playback fails. Do not troubleshoot permissions on stage.
4. For a brief recovery attempt use **Talk / reconnect**. Repeated starts abort the previous
   recognizer; reset/navigation removes old handlers so late transcripts cannot reopen a run.

## If web search fails

Stage mode deliberately uses the dated curated catalogue, so an API outage or web-search
rate limit does not interrupt it. Click **Start background research**, continue talking and
show the five completed topics. Say “These are our reviewed source-list results.” Do not
call them live search results or claim their contact/availability details are current.

The normal live-stack scenario also supports `mode: snapshot`. For a separate live-stack
rehearsal, build with `DEMO_MODE=false`, start the existing Docker/backend stack and use
`/demo/founder-arrival`. Its **Start a fresh run** is a different, server-session reset.
Run `backend/scripts/demo_founder_arrival.py --twice` before relying on that path. Do not
switch builds or backend modes during the stage presentation.

## If document vision or document preview fails

Click **Upload demo documents**. These specimens have readable PDF text and a validated
passport MRZ, so cloud vision is unnecessary. If the public PDF fetch fails, ADAPT shows
“Document preview unavailable. Continuing with the verified synthetic extraction replay.”
The recorded fields, twin and plan remain available. Explain that this is the validated
specimen replay; do not claim a new live OCR/VLM result. Never upload a real passport.

## Recovery, persistence and limits

- Refresh retains chapter, synthetic approval, branch and research start time. A running
  research replay resumes from elapsed time; it does not restart a search. Replies and raw
  transcripts are not retained.
- `/documents`, `/knowledge/me`, `/knowledge/governance`, `/agents`, `/journey`, `/discover`,
  `/simulate` and `/home` deep-link to their corresponding demo chapters. They work offline
  after the PWA shell has been warmed once. First-ever offline loading is not supported.
- A mobile browser uses the same Continue/Back controls; desktop chapter navigation stays
  in the sidebar. Reduced-motion settings turn off graph and agent pulse animations.
- Installability can be checked automatically; actually installing on the presenter's
  device and testing its speakers/microphone require pre-stage manual rehearsal.
- No frontend mode can guarantee a healthy external provider. This mode's resilience comes
  from its explicitly labeled recorded results, not undisclosed fabricated responses.

## Regenerating the synthetic replay

Only regenerate before rehearsal, never on stage:

```powershell
cd backend
.\.venv\Scripts\python.exe scripts/build_demo_replay.py
cd ..
npm test
npm run demo:build
npm run audit:demo
```

The script uses the real LangGraph with in-memory demo ports and the existing test harness,
not production database accounts. It writes `frontend/src/features/demo/replay.json` and
the matching public SPECIMEN PDFs with SHA-256 checksums. UUIDs, event timestamps and PDF
metadata may change on regeneration; planner counts and branch relationships are checked
by the integrity tests. Source-check dates are preserved rather than replaced with today.
