"""The refbot HTTP app and the HTTP adapters agree on the contract."""

import asyncio

import httpx
import numpy as np


def test_audio_and_text_contract():
    from refbot.app import app
    from chakravyuh.adapters.http import AudioHTTPBot, TextHTTPBot
    from chakravyuh.clients import build_clients
    from chakravyuh.config import get_settings

    transport = httpx.ASGITransport(app=app)

    async def go():
        bot = AudioHTTPBot("http://refbot/v1", version="v1")
        bot._http = httpx.AsyncClient(transport=transport)
        sid, greet = await bot.start_call()
        assert greet.audio is not None and len(greet.audio) > 0
        assert "Dhan Seva" in greet.text_true
        r = await bot.turn(sid, np.zeros(8000, dtype=np.float32), 8000)
        assert r.audio is not None
        await bot.end_call(sid)

        c = build_clients(get_settings())
        tb = TextHTTPBot("http://refbot/v2", c.stt, c.tts, version="v2")
        tb._http = httpx.AsyncClient(transport=transport)
        sid, g = await tb.start_call()
        r = await tb.turn(sid, np.zeros(8000, dtype=np.float32), 8000, reference_text="OTP aaya hai 000913, le lo.")
        assert "OTP" in r.text_true or "otp" in r.text_true.lower()

    asyncio.run(go())
