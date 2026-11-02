# Great Indian AI Internship Challenge: research and ideas

_Researched 2 Nov 2026. Deadline: **10 Nov 2026, 11:59 PM IST** (8 days)._

## 1. What the contest actually rewards

| Lever | What it means for us |
|---|---|
| **Must use Gnani models** | Prisma (STT), Timbre (TTS), Evon v3.3 (30B-A3B open-weight reasoning). Using **all three**, and using them deeply, is the clearest signal. |
| **Selection = LinkedIn/X engagement** | They verify reactions, comments and reshares on the posts you nominate. The demo video is half the product. |
| **Then interviews** | Each person is interviewed alone. The build has to show engineering depth you can defend: latency numbers, evals, design trade-offs. |
| **10 awards (₹50k each)** | Regional languages · Hinglish/code-mixed · **noisy telephonic audio** · real-world impact · solo/duo · creativity · Tier 2/3 · **best 60-second demo** · Crowd Favourite (public vote). |
| **Hashtags** | `#GnaniAI` `#GreatIndianAIInternshipChallenge`. Tagging Gnani alone doesn't count; the post must be live before you submit. |
| **Eligibility** | Enrolled student in India, 18+, solo or one teammate. |

**Gnani's business** (what interviewers care about): voice agents for contact centres (30M+ calls a day, 200+ enterprises; BFSI customers such as HDFC, Bank of Baroda, IDFC and Muthoot, plus Airtel and Tata Motors). Products: Inya (no-code agent builder), Automate365 (AI agents), Assist365 (live agent assist), Aura365 (call QA analytics), Armour365 (voice biometrics). Their pain points: **telephony audio at 8 kHz, code-mixing, and agents that break in production.**

## 2. API facts (from Gnani's official LiveKit plugin source)

- Base URL `https://api.vachana.ai`, header `X-API-Key-ID`.
- **Prisma STT:** REST `POST /stt/v3` (multipart, `language_code`), **streaming WebSocket `wss://api.vachana.ai/stt/v3/stream`** (headers `lang_code`, `x-sample-rate` ∈ {**8000**, 16000, 44100, 48000}, optional `itn_native_numerals`). Languages: bn, en, gu, hi, kn, ml, mr, pa, ta, te (`-IN`), and `"en-IN,hi-IN"` auto-detects code-mixed speech.
- **Timbre TTS:** `timbre-v2.0` / `timbre-v2.5`, REST and SSE streaming. Voices include Pranav, Kaveri, Shubhra and Deepak. The `language` setting works only on v2.5 (same 10 languages + `auto`). Output is PCM/Opus as raw, mp3, wav or ogg at 8–44.1 kHz. The quick start mentions **voice-cloning embeddings** (still to be verified on the dashboard).
- **Evon v3.3:** `gnani/gnani-evon-v3.3-30B-A3B` on Hugging Face, 128K context, reasoning toggle, 10 Indic languages. It isn't on the credit API, so we have to serve it ourselves (vLLM on a rented GPU, Friendli, or a GGUF quantisation).

## 3. Competition scan (≈80 public GitHub repos already)

Areas that are already crowded, so we should **avoid** them:
- Scam-call shields (Kavach ×3, scam-call-shield, CallSuraksha, VoiceShield…)
- Kirana/shop voice ledgers (kirana-khata, bolo-bill, ugharani, bharat-bazaar, vyapaar-vani…)
- Farmer helplines, government-scheme finders, voice form-filling (Bolo, janvaani, sarkari-saathi, Kaagaz-Saathi…)
- Customer-support RAG bots (dozens of "ZentroMart VoiceOps" course capstones)
- Legal help, health intake, English/reading tutors, civic complaint lines

**Nobody is building tools that test or stress voice agents, and nobody is doing a creator dubbing pipeline.** Those are the gaps.

## 4. Ideas

### ⭐ A. CHAKRAVYUH: crash-test dummies for Indian voice agents (recommended)
An army of synthetic Indian callers that phone a voice bot and try to break it, then hand back a report card.
- **Personas from Evon:** an impatient Delhi uncle, a Chennai aunty mixing Tamil and English, a farmer on a 2G line, a student speaking fast Hinglish, an elderly caller who asks for repeats, a customer who keeps interrupting, a social engineer trying to get account details out of the bot.
- **Timbre speaks each persona** in 10 languages. A **telephony degradation layer** downsamples to 8 kHz and adds codec artefacts, packet loss, train/traffic/crowd noise, and barge-in timing.
- **Prisma hears the bot's replies** through the same bad channel (streaming, 8 kHz).
- **Evon acts as judge:** task success, hallucinated policy, language-switch handling, PII leaks, and turns to resolution. We also measure latency and dead air.
- **Output:** a red/amber/green scorecard with audio clips of every failure, and a comparison across bot versions (regression testing for voice).
- **Why it wins:** it targets Gnani's core business (they ship bots for 200 enterprises, and QA is the pain). It covers the **noisy telephony** and **Hinglish** awards, uses all three models deeply, and gives you real numbers to talk through in the interview. The hook also travels well online: *"I built 50 angry Indian uncles to call a bank's chatbot."*
- **Demo (60 s):** a split screen. On the left, the "Uncle on a train" persona calls a mock bank bot. On the right, the live transcript, then the failure, then the scorecard turning red. End on a leaderboard.

### B. EK AWAAZ: dub yourself into 10 Indian languages in your own voice
A creator records a reel in one language. We transcribe it with Prisma (with timestamps), have Evon do **length-matched, code-mix-aware translation** (keeping "EMI", "UPI" and brand names as they are), then clone the voice with Timbre, time-stretch the audio to the original timing, and remux the video.
- **Why it spreads:** the LinkedIn demo post is the product itself. You say one sentence and then speak Tamil, Bengali and Marathi. Creators reshare tools like this, and it fits the Crowd Favourite and Creativity awards.
- **Risk:** it depends on Timbre voice cloning, which is in beta. Check this on day 1 before committing. Lip sync is out of scope.

### C. DO-BHASHI: a live interpreter for phone calls
A Tamil-speaking patient calls a Hindi-speaking doctor, and each hears the other in their own language in near real time. The pipeline is streaming STT, then Evon translating incrementally, then streaming TTS, tuned for latency (target under 1.5 s per turn).
- Strong for the real-world impact and regional-language awards. The hard part is latency, and that is good material for the interview.

### Wildcards (fun, viral, lower enterprise value)
- **Mol-Bhav Arena:** practise haggling against an AI Sarojini Nagar shopkeeper in Hinglish, with a scored negotiation. Strong Creativity and Crowd Favourite candidate.
- **Dadi ki Kahaniyaan:** record grandparents' oral stories in dialect, transcribe and archive them, and let grandkids ask questions that get answered from the stories. Very emotional, and LinkedIn responds to that.
- **2G Internet:** a phone number you call from a feature phone to ask anything, aimed at Tier 2/3 users with no data plan. Fits the telephony and Tier 2/3 awards, but sits closer to the helpline category, which is getting crowded.
- **Shayari/rap battle:** trade Hinglish bars with Evon and Timbre.

## 5. Recommendation

Build **A (Chakravyuh)** as the core product. It is the most defensible in an interview, it is uncontested, and it maps directly onto Gnani's revenue. Borrow B's playbook for the launch: make the demo funny and loud, and post a teaser before the main video.

## 6. Eight-day plan (A)

| Day | Work |
|---|---|
| 2 Nov | Get API keys, smoke-test STT REST/WS and TTS (all languages, 8 kHz), stand up Evon (vLLM or Friendli). |
| 3 Nov | Telephony degradation pipeline. Persona engine (Evon) to Timbre. Mock target bot (a "bank EMI bot" with planted bugs). |
| 4 Nov | Conversation loop: caller to bot over a WebSocket "phone line", Prisma transcription, turn-taking and barge-in. |
| 5 Nov | Evon judge, metrics (success, latency, dead air, PII leak, language handling), and a scorecard UI. |
| 6 Nov | Polish the dashboard and failure clips; prove a regression diff between bot v1 and v2. Post the teaser. |
| 7 Nov | Record the 60-second demo plus a 2-minute deep-dive. README with architecture and numbers. |
| 8 Nov | Launch the post. Engage every comment in the first 2 hours; teammates and friends reshare. |
| 9–10 Nov | Follow-up posts ("what broke the most bots"), then submit before 11:59 PM IST on 10 Nov. |

## 7. Engagement playbook
- Hook in the first line and in the first 2 seconds of the video. Subtitles on, since most people watch muted.
- Post natively (upload the video, don't link to YouTube). Put the GitHub link in the first comment.
- Post a teaser 2–3 days before the main launch, then a "results" follow-up.
- Reply to every comment quickly. Ask a question at the end of the post to invite comments.
- Credit Gnani's models by name, because they're likely to reshare work that makes Prisma look robust.
