# Mission: win the Gnani AI "Great Indian AI Internship Challenge" (2026)

You are the lead strategist and architect on this project. You have full authority to decide **what** we build. Everything below is context, not a constraint. A previous research pass suggested some ideas; treat them as **one opinion you can validate, improve, merge, or throw away completely**. If you find a better idea, propose that instead and argue for it.

---

## 1. The goal
Get me (an enrolled student in India) **shortlisted for an interview and a written internship offer at Gnani AI**, a paid 6-month internship with a stipend of up to ₹1 lakh/month. Win one or more of the ₹50,000 award categories along the way if we can.

## 2. The outcome we need by the deadline
1. **A working project built on Gnani's voice models**, with a public GitHub repo and a README that shows real engineering depth.
2. **A public demo video posted on LinkedIn and/or X** with `#GnaniAI` and `#GreatIndianAIInternshipChallenge`. This is a hard rule: tagging Gnani alone doesn't count, and the post must be live before submission.
3. **High verified engagement on that post** (reactions, comments, reshares). Gnani has said it selects "on the basis of popular engagement on LinkedIn or X", so the post is as important as the product.
4. **A build I can defend alone in an interview.** Each team member is interviewed separately and offers are individual.
5. **Submission** through Gnani's submission form, nominating the posts. Reported deadline: **10 Nov 2026, 11:59 PM IST** (verify this). Today is 2 Nov 2026.

## 3. Read these sources first (the previous pass could NOT reach them, so verify everything below against them)
- Challenge page: https://www.gnani.ai/internship
- Challenge blog: https://www.gnani.ai/resources/blogs/great-indian-ai-internship-challenge-2026
- Registration form: https://www.gnani.ai/great-indian-ai-internship-registration-form
- API platform / dashboard (keys, testing voices and languages): https://app.gnani.ai
- API docs: https://docs.gnani.ai (start at https://docs.gnani.ai/api/introduction/introduction and https://docs.gnani.ai/api/introduction/quick-start)
- Evon model card: https://huggingface.co/gnani/gnani-evon-v3.3-30b-a3b
- Gnani's main site and product pages: https://www.gnani.ai (look at Inya, Automate365, Assist365, Aura365, Armour365, and the case studies)
- Sweep the **whole** gnani.ai site, especially the full rules/terms, the FAQ, the award categories, any judging criteria, Discord/support links, and any hints about what the team values.

## 4. What I was told (from the challenge page screenshots, verify all of it)
- **Build resources:** 5,000 programme credits on the API platform; 3 free API keys.
- **Models:** Prisma (speech-to-text), Timbre (text-to-speech, beta), Evon (a 30B-parameter reasoning model on Hugging Face). The project **must** use Gnani models/APIs.
- **What to do:** you can build any app, workflow or solution; the only requirement is using Gnani's voice models.
- **Selection:** public demo on LinkedIn/X, then Gnani verifies engagement on the nominated posts, then shortlisting, then individual interviews, then written offers.
- **Stipends** are per intern, not split. Offers are individual. Gnani can change rules, timelines and prizes at any time.
- **Award categories (10):** regional languages; Hinglish and other code-mixed voice experiences; noisy telephonic audio; real-world impact; best solo or duo project; creativity; entries from Tier 2 and Tier 3 towns; best 60-second demo; public-vote Crowd Favourite (plus whatever the site lists that I missed).
- **Reported from third-party pages (unverified):** up to 100 internships starting 1 Jan 2027; ten ₹50k awards; solo or one teammate; 18+ enrolled students in India; the brief asks for "a practical need for enterprises, developers or creators"; current versions are Prisma v2.5, Timbre v2.5 and Evon v3.3.

## 5. Technical notes the previous pass gathered (from Gnani's official `livekit-plugins-gnani` source on PyPI; verify against the docs)
- Base URL `https://api.vachana.ai`; auth header `X-API-Key-ID`.
- **Prisma STT:** REST `POST /stt/v3` (multipart, `language_code`). Streaming over WebSocket at `wss://api.vachana.ai/stt/v3/stream`, with headers `lang_code`, `x-sample-rate` (8000 / 16000 / 44100 / 48000) and optional `itn_native_numerals`. Languages: bn, en, gu, hi, kn, ml, mr, pa, ta, te (all `-IN`); `"en-IN,hi-IN"` auto-detects code-mixed speech.
- **Timbre TTS:** `timbre-v2.0` and `timbre-v2.5`, REST and SSE streaming, with SSML. Voices include Pranav, Kaveri, Shubhra and Deepak (more per model). The `language` parameter works on v2.5 only. Output is linear PCM or Opus as raw, mp3, wav or ogg at 8–44.1 kHz. The quick start mentions **voice-cloning embeddings**, so check whether cloning is actually usable.
- **Evon v3.3:** `gnani/gnani-evon-v3.3-30B-A3B` (MoE, about 3B active parameters), 128K context, reasoning toggle, English plus 10 Indic languages. It does **not** appear to be on the credit API, so it probably has to be self-hosted (vLLM on a rented GPU, Friendli, or a third-party GGUF quantisation). Confirm this.

## 6. Who Gnani is (why the interviewers care about certain things)
- A Bengaluru voice-AI company with a Series B (~$10M, Aavishkaar, 2026). It claims 30M+ voice-AI calls a day for 200+ enterprises across BFSI, telecom, healthcare, automotive and government (HDFC Bank, Bank of Baroda, IDFC First, Indian Bank, Muthoot, Airtel, Tata Motors, Hyundai and others).
- Products: Inya (no-code agent builder, and Inya VoiceOS speech-to-speech), Automate365 (AI agents), Assist365 (live agent assist), Aura365 (post-call QA analytics), Armour365 (voice biometrics).
- Their hard problems: 8 kHz telephony audio, noise, code-mixing across Indian languages, latency and barge-in, and voice agents failing in production.

## 7. Competition (about 80 public GitHub repos found on 2 Nov; re-scan GitHub and the LinkedIn hashtag yourself)
Already crowded:
- scam/fraud call shields (5+)
- kirana/shop voice ledgers and order bots (5+)
- farmer and agri helplines
- government-scheme finders and voice form-filling
- dozens of "ZentroMart VoiceOps" customer-support RAG bots (an IIT Guwahati × Gnani course capstone)
- legal-aid bots, health intake and discharge follow-up, English and reading tutors, civic complaint lines
- ride-app voice translation, accessibility assistants, astrology bots

Look at what's getting engagement on `#GreatIndianAIInternshipChallenge` right now and what isn't.

## 8. Ideas from the previous pass (non-binding; validate, steal from, or reject)
- **A. CHAKRAVYUH, crash-test dummies for Indian voice agents.** Evon-generated caller personas (an impatient uncle, a Tamil-English aunty, a farmer on 2G, an elderly caller, an interrupter, a social engineer) speak through Timbre over a simulated 8 kHz noisy phone line. They call a voice bot, Prisma transcribes the bot through the same channel, and Evon judges task success, hallucination, PII leaks, language handling, latency and dead air. The output is a scorecard with failure clips and a regression diff between bot versions. Rationale: it maps onto Gnani's core business, competes for the telephony and Hinglish awards, and the interview story is strong. Hook: "I built 50 angry Indian uncles to call a bank's chatbot."
- **B. EK AWAAZ, dub yourself into 10 Indian languages in your own voice.** A creator reel goes through Prisma, then Evon does length-matched code-mix-aware translation, then Timbre clones the voice, then the audio is time-aligned and the video remuxed. The viral loop: the demo post is the product. Risk: depends on Timbre voice cloning in beta.
- **C. DO-BHASHI, a live two-way phone interpreter.** Each party hears the other in their own language; target under 1.5 s per turn.
- **Wildcards:** a Hinglish haggling game against an AI shopkeeper; preserving grandparents' oral stories in dialect; a 2G "voice internet" you can call from a feature phone; a Hinglish shayari/rap battle.

The previous recommendation was A as the product with B's viral launch style. **You are free to disagree.**

## 9. What I want from you
1. **Verify** the rules, deadline, award categories, API capabilities and credit costs from the live sources above. Flag anything that contradicts this brief.
2. **Brainstorm without limits.** Go wide first, with wild and unconventional ideas, then converge. Stress-test my ideas and yours against every criterion below, and say plainly which ones are weak and why.
3. **Pick one winner**, or a combination, and justify it against:
   - (a) LinkedIn/X virality and the 60-second demo
   - (b) interview depth and relevance to Gnani's business
   - (c) how many award categories it can credibly compete for
   - (d) originality versus the field above
   - (e) feasibility for 1–2 people in the remaining days with 5,000 credits
   - (f) how deeply it uses Prisma, Timbre and Evon
4. Give me the **architecture, tech stack, day-by-day build plan to the deadline, risks with fallbacks**, a **storyboard for the 60-second demo video**, and the **LinkedIn post copy plus engagement strategy** (teaser, launch, follow-ups).
5. Then start building it.
