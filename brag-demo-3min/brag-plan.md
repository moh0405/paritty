# Paritty 3-minute walkthrough

Long-form cut (4m02s, 1920x1080) requested after the 21s brag. Polished tone, 14 chapters:
hook (36+ days), how a trial runs, the idea, Today and roles, data checks and queries,
safety and lab reconciliation, liver signals (eDISH), site risk, lock forecast, protocol
assistant / data hub / accuracy tests, Gemini (draft, verify, approve), Tiger Data (one Postgres,
forking for evals), five guardrails, outro.

Grounding: names, labels and tagline come from the app source (`frontend/app/*`,
`Sidebar.tsx`, `ROLE_LABELS`) and `docs/PROJECT_EXPLAINER.md`. UI scenes carry an
"Illustrative sample data" tag; all values are fictional stand-ins.

Audio: ~4:10 music bed made from "Happy Beats / Business Moves" vol-1 crossfaded into vol-12
(ende.app), low volume, 12 sparse motion-matched SFX (Kenney, CC0). Beat-locking and
audio-reactive visuals were not used for this cut.

Rebuild: `cd composition && npx hyperframes render --output ../brag.mp4` (Node >= 22, ffmpeg).

Gemini and Tiger chapters are grounded in `docs/PROJECT_EXPLAINER.md`, `docs/DECISIONS.md` and
`docs/TIGER.md`. They describe what the system does; they do not quote accuracy numbers, because
several Gemini paths were not recorded against live output (free-tier quota) per DECISIONS.md.
