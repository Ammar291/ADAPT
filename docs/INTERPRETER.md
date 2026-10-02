# ADAPT Interpreter

Open `/interpreter`, or `/interpreter?source=en&target=ar`. This is a standalone human-to-human interpreter. It has its own backend service, provider interface, WebRTC transport, controller, UI, transcripts, and events. It does not import the assistant controller, tools, RAG, knowledge graph, or LangGraph. The existing assistant keeps its original endpoints and behavior. Authentication, the HTTP client, design tokens, and the PWA shell are shared infrastructure.

## Language support

The provider exposes `/api/interpreter/capabilities`. Both directions are validated on the server before creating credentials. The UI reads that response; unsupported pairs cannot start.

The [official OpenAI translation guide](https://developers.openai.com/api/docs/guides/realtime-translation) specifies the dedicated translation flow. The [OpenAI cookbook language list](https://developers.openai.com/cookbook/examples/voice_solutions/realtime_translation_guide) currently lists thirteen output languages, including English and Hindi, but **not Arabic**. Arabic is a supported input language. Consequently:

| Pair | A → B | B → A |
| --- | --- | --- |
| English ↔ Hindi | `gpt-realtime-translate` / WebRTC | `gpt-realtime-translate` / WebRTC |
| English ↔ Arabic | Recorded speech → transcription → text translation → TTS | `gpt-realtime-translate` / WebRTC |
| Arabic ↔ English | `gpt-realtime-translate` / WebRTC | Recorded fallback |

Arabic output is labeled as recorded translation in the language selector and on the page. It is not advertised as realtime. Disabling the fallback disables this bidirectional pair with an explanation. The target language is configured server-side; the realtime model detects the spoken input language. Speaking in the selected target language may produce no translated audio.

There is no documented OpenAI language-discovery endpoint. `provider.py` contains the documented capability snapshot, checked on 2026-10-02. Update that snapshot when the provider changes its capabilities. Account/model access and language rejection remain authoritative at session creation; an upstream rejection surfaces an error and the recorded option remains available. No arbitrary language-pair guarantee is made.

## Environment

Set these in the existing repository-root `.env`. Docker already passes that file to the backend.

| Variable | Default | Purpose |
| --- | --- | --- |
| `OPENAI_API_KEY` | empty | Server-only primary key. Required for live speech and fallback. Never use a `VITE_` key variable. |
| `INTERPRETER_MODE` | `auto` | `auto`: live when credentials exist, demo otherwise. `live`: error if credentials are absent. `demo`: scripted samples. Independent of `ADAPTER_VOICE`. |
| `INTERPRETER_FALLBACK_ENABLED` | `true` | Enables recorded translation, including Arabic output. |
| `INTERPRETER_TRANSCRIPTION_MODEL` | `gpt-4o-mini-transcribe` | Recorded fallback transcription only. |
| `INTERPRETER_TRANSLATION_MODEL` | `gpt-5.4-mini` | Recorded fallback text translation only. |
| `INTERPRETER_TTS_MODEL` | `gpt-4o-mini-tts` | Recorded fallback speech, with a fixed `coral` voice. |
| `REDIS_URL` | existing app default | Independent interpreter spending limits and session revocation. Failure disables new sessions and fallback requests. |
| `SESSION_SECRET` | existing app configuration | Derives a separate interpreter signing key; binds lifecycle tokens to tenant/user and language pair. |
| `OPENAI_BASE_URL`, `OPENAI_ORGANIZATION` | existing defaults | Optional server client configuration. Browser SDP remains restricted to the official OpenAI translation endpoint. |

Realtime uses exactly `gpt-realtime-translate` and source transcripts use `gpt-realtime-whisper`. Assistant model/voice environment variables do not configure the interpreter. Realtime translation receives no assistant prompt, tools, `response.create`, or fixed output voice.

## Session and audio flow

1. The page loads capabilities without requesting microphone permission.
2. Start requests an audio-only microphone with echo cancellation, noise suppression, automatic gain control, and mono capture. Explicit demo mode does not request a microphone.
3. The authenticated browser posts `{source, target, recorded?}` to `/api/interpreter/session`. The server validates both directions, applies a per-user limit of ten session/reconnect requests per minute, and issues a signed interpreter lifecycle token valid for one hour.
4. For each realtime direction, the backend creates an independent 120-second credential at `/v1/realtime/translations/client_secrets`. The primary API key stays on the backend. The installed SDK currently lacks the translation resource, so the adapter uses its supported generic POST to the official endpoint/schema; it prefers the dedicated SDK resource when available.
5. Each participant gets a separate `RTCPeerConnection`, microphone track, remote audio stream, and `oai-events` data channel. The browser posts SDP to `/v1/realtime/translations/calls` using only that direction's short-lived credential. Source and translation captions come from `session.input_transcript.delta` and `session.output_transcript.delta`, respectively. Deltas append verbatim, without inserted spaces; event IDs prevent duplicate delivery.
6. A lost connection triggers up to three attempts with fresh credentials from `/api/interpreter/reconnect`. Inputs are gated throughout recovery. Captions and selected-speaker/mute/pause settings survive. Credential expiry limits the initial handshake, not an already established call. Provider session expiry triggers renewal; expiry of the signed lifecycle token requires a new conversation.
7. End, route unmount, and `pagehide` cancel pending work, close both peer connections, stop every captured/cloned microphone track, disconnect audio nodes, revoke replay URLs, and request session revocation at `/api/interpreter/end`. Credentials already handed to the browser cannot be revoked by this app; the peer connections are closed locally and credentials expire after 120 seconds.

On a shared phone or laptop microphone, **select You or Other person before that person speaks**. Only the selected source is enabled. This is explicit speaker routing, not automatic diarization. Overlapping voices on one physical microphone cannot be isolated. Optional two-microphone mode requires distinct device IDs and verifies that the browser did not resolve both choices to the same input. It still enables only the selected speaker.

Default speaker mode analyses raw remote audio and adds 120 ms of playback buffering. This gives the microphone gates time to close before translated sound reaches the speakers. Gates remain closed through a quiet tail. Remote audio and replay tracks are never attached to either microphone sender or mixed into an input stream. Browser acoustic echo cancellation complements the gates. Headphone mode permits continuous speech while translation plays; choose it only with headphones. Replay pauses microphones even in headphone mode. Actual room acoustics and headset routing still need device testing.

## Recorded fallback and subtitles

Arabic output uses an explicit Record / Translate control. A phrase is capped at 25 seconds; the backend accepts up to 4 MB of WebM, MP4, or Ogg audio. Only the selected speaker's microphone is recorded. The server transcribes, translates without tools or conversation history, and requests TTS. A separate setting can use this fallback for both directions after realtime failure. It never silently replaces working realtime streams.

If TTS fails after translation succeeds, the response retains original and translated text. If browser playback is blocked, Enable audio gives the user a new playback gesture; subtitles remain available. If realtime audio is lost while transcript deltas still arrive, those deltas continue rendering independently of playback.

Original and Translation have separate labels, language attributes, and containers. Arabic text uses RTL independently of the page layout. Subtitles can be hidden without deleting in-memory text. Realtime captions are continuous streams, not falsely aligned chat turns. Each pane retains its latest 6,000 characters. Reconnect retains those captions; a new conversation or swap clears them.

Replay uses the latest completed local remote-audio recording where `MediaRecorder` supports it. It may omit the first monitor interval and is not promised to be a byte-exact full utterance. Recorded fallback replay uses the returned TTS audio. Replay is disabled until a valid local audio blob exists. Transcripts and replay blobs are never put in localStorage, analytics payloads, or the service-worker cache. Uploaded audio is processed transiently and closed after each request; framework upload buffering may use temporary files. The app does not persist interpreter conversations. Fallback Responses calls use `store=False`.

## States and events

The controller exposes Idle, Connecting, Listening, Translating, Speaking, Paused, Reconnecting, Stopped, and Error through `getSnapshot()` / `subscribe()` and React's `useSyncExternalStore`. Muted is a separate flag, shown explicitly alongside state. Speaking is derived from actual audio activity/playback, not merely receipt of text. Demo mode never emits successful audio playback.

Listen for these window events or use the controller callback:

```js
window.addEventListener('translation_received', ({ detail }) => {
  // { name, speaker: 'a' | 'b', state, timestamp, demo, code? }
  // No transcript text, API credentials, or recordings are included.
});
```

Events: `interpreter_started`, `speaker_detected`, `translation_started`, `translation_received`, `audio_playing`, `translation_completed`, `reconnecting`, `interpreter_error`, `interpreter_stopped`. Completion is an app-level quiet boundary because the translation service streams continuously and has no voice-assistant turn lifecycle.

## Local development and PWA

Use the existing full-stack startup from the README. With native development:

```powershell
# Repository root: start existing Postgres and Redis as documented in README.
# In one terminal:
cd backend
uv run uvicorn app.main:app --host 127.0.0.1 --port 8100 --reload
# In a second terminal at the repository root:
npm run dev
```

Open `http://localhost:5180/interpreter?source=en&target=hi` for realtime, or `?source=en&target=ar` for hybrid Arabic output. Use the app's existing authenticated session. With no backend or credentials, open `/interpreter?source=en&target=ar&demo=1`; this bypasses private-workspace startup and never calls the API or captures audio. Demo samples are explicitly labeled and do not represent live translation or product actions.

Microphone capture requires **HTTPS or localhost**. Plain HTTP over a phone's LAN IP is not a secure context. Use an HTTPS development endpoint for Android/iOS device testing, and configure the existing public URL and trusted origins. Do not disable origin checks. Production nginx already permits same-origin microphones, OpenAI SDP requests, and local blob audio. Keep those permissions and CSP rules when deploying.

Chrome Android, Safari iOS, and installed PWAs must obtain OS and site microphone permission separately when required. Safari may require a tap on Enable audio after remote media arrives. MP4 recording is used when WebM is unavailable. Backgrounding pauses input; explicitly Resume on return. If the OS has ended the microphone track, start a new session. The interpreter shortcut is included in the PWA manifest, and its page code is precached. Audio, secrets, uploads, and API responses remain network-only. Live translation requires a connection even when the shell is installed/offline.

## Verification

```powershell
npm run typecheck
npm test
npm run build
cd backend
uv run pytest tests/unit/test_interpreter.py tests/unit/test_voice.py -q
# In a sandbox, choose a fresh workspace --basetemp and -p no:cacheprovider if required.
# Back at repository root, with Playwright installed or ADAPT_PLAYWRIGHT_MODULE set:
npm run audit:interpreter
```

The browser audit can use `ADAPT_PLAYWRIGHT_MODULE` (a Playwright module path) and `ADAPT_BROWSER_EXECUTABLE` (Chromium executable). It uses a fresh isolated profile under `var`, installs/launches/uninstalls a test PWA, and writes its report/screenshots under `frontend/qa-artifacts/interpreter`. All translation and backend responses in that audit are synthetic fixtures. Chromium microphone capture, playback, remote-track recording, and standalone PWA mode are real browser APIs. The audit does not assess OpenAI translation quality.

Verified on 2026-10-02: frontend tests, interpreter/assistant backend regression tests, TypeScript and production build, provider endpoint/schema/security tests, English ↔ Arabic and English ↔ Hindi demo flows, real Chromium microphone capture with a simulated translation transport, speaker playback gates, replay, denial handling, subtitle rendering, fallback audio, device release, installability, and an installed Chromium standalone PWA using microphone/playback. See the generated audit report for exact results.

**Remaining live acceptance checks:** no external key was present, so live OpenAI speech translation/quality and real Android/iOS hardware were not verified. Before release, use bilingual speakers to test English ↔ Hindi realtime and English ↔ Arabic hybrid speech, numbers/names, low latency with headphones, speakerphone feedback in the expected room, autoplay denial/recovery, Wi-Fi/cellular handover, permission revocation, screen lock/resume, and installed Android/iOS PWA playback. Do not describe the recorded English → Arabic direction as realtime.

## Replacing the provider

Implement `TranslationProvider.capabilities`, `credential`, and `translate_recording` in the independent backend interpreter package. Supply the corresponding browser `TranslationConnection` factory and trusted endpoint validation if the replacement transport differs. The controller accepts API/audio/connection dependencies for tests and alternate transports. No assistant, graph, journey, or action integration is needed.
