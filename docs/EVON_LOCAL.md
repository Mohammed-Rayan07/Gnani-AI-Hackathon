# Evon v3.3 as the second judge (free, on your laptop)

Evon (`gnani/gnani-evon-v3.3-30B-A3B`) is open weights (Apache-2.0, not gated) and is not on the credits API. It is a MoE model with about 3B active parameters, so a quantised GGUF runs acceptably on a laptop with mixed GPU and CPU offload.

The calls are already logged, so judging with Evon never re-runs a call and costs **no Gnani credits**. Evon re-judges the saved transcripts, and `chakravyuh agree` publishes how often it agrees with the primary judge.

## 1. Run it (pick one)
**Ollama** (simplest):
1. Install from ollama.com.
2. Find a quantisation on huggingface.co/luminenio/gnani-evon-v3.3-30B-A3B-GGUF (Files tab).
   - With 16 GB RAM and 6 GB VRAM, prefer **Q3_K_M or IQ4_XS** (14 GB or less).
   - Q4_K_M is around 18 GB and will page.
3. Pull and run it:
```
ollama run hf.co/luminenio/gnani-evon-v3.3-30B-A3B-GGUF:Q3_K_M
```
The OpenAI-compatible endpoint is `http://localhost:11434/v1`. The model name is exactly what `ollama list` shows.

**llama.cpp** (if Ollama fails to load the `nemotron_h` architecture, or to switch reasoning off):
```
llama-server -m <file>.gguf -c 16384 -ngl 99 --n-cpu-moe 40 --port 8080
```
- The endpoint is `http://localhost:8080/v1`.
- Lower `--n-cpu-moe` if your VRAM has room to spare.
- To switch reasoning off, set `EVON_LLM_EXTRA_BODY={"chat_template_kwargs": {"enable_thinking": false}}`.

## 2. .env
```
EVON_LLM_BASE_URL=http://localhost:11434/v1
EVON_LLM_MODEL=<name from `ollama list`>
EVON_LLM_API_KEY=
# EVON_LLM_JSON_MODE=false   # if the server rejects response_format
```

## 3. Use it
```
uv run chakravyuh judge runs/<run> --judge evon     # writes verdicts.evon.json, never overwrites the primary
uv run chakravyuh agree runs/<run>                  # kappa(primary judge, Evon), overall and per criterion
```
Smoke-test it on one small run first and note the seconds per call. If one call takes more than about 2 minutes, judge a subset with Evon (for example, all `kyc_otp_pressure` calls), and say in the README that only that subset was judged.
