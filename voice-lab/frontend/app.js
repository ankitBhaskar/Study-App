const API_BASE = import.meta.env.VITE_VOICE_API_URL || 'http://localhost:8010';

const providerEl = document.querySelector('#provider');
const voiceEl = document.querySelector('#voice');
const speedEl = document.querySelector('#speed');
const textEl = document.querySelector('#text');
const countEl = document.querySelector('#count');
const errorEl = document.querySelector('#error');
const generateBtn = document.querySelector('#generate');
const compareBtn = document.querySelector('#compare');
const sampleBtn = document.querySelector('#sample');

const estimateCost = (provider, chars) => {
  const tenMinuteChars = 9000;
  const estimatesAud = { gemini: 0.5, openai: 0.03, elevenlabs: 1.0 };
  const value = (chars / tenMinuteChars) * estimatesAud[provider];
  return `A$${Math.max(value, 0.01).toFixed(2)}`;
};

const updateCount = () => {
  countEl.textContent = `${textEl.value.length.toLocaleString()} characters`;
};

const setError = (message) => {
  errorEl.hidden = !message;
  errorEl.textContent = message || '';
};

const cardFor = (provider) => document.querySelector(`.card[data-provider="${provider}"]`);

const setCard = (provider, state) => {
  const card = cardFor(provider);
  card.querySelector('.status').textContent = state.status;
  if (state.audioUrl) card.querySelector('audio').src = state.audioUrl;
  if (state.details) {
    card.querySelector('dl').innerHTML = Object.entries(state.details)
      .map(([key, value]) => `<dt>${key}</dt><dd>${value}</dd>`)
      .join('');
  }
};

const generateFor = async (provider) => {
  setError('');
  setCard(provider, { status: 'Generating audio...', details: {} });
  const started = performance.now();
  const response = await fetch(`${API_BASE}/api/voice/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ provider, text: textEl.value, voice: voiceEl.value.trim() || null, speed: Number(speedEl.value || 1) }),
  });

  if (!response.ok) {
    const detail = await response.text();
    setCard(provider, { status: 'Failed', details: { Error: detail.slice(0, 240) } });
    throw new Error(`${provider} failed`);
  }

  const blob = await response.blob();
  const audioUrl = URL.createObjectURL(blob);
  const elapsed = Math.round(performance.now() - started);
  setCard(provider, {
    status: 'Success',
    audioUrl,
    details: {
      Model: response.headers.get('X-Voice-Model') || 'Unknown',
      Latency: `${response.headers.get('X-Voice-Latency-Ms') || elapsed} ms`,
      Size: `${blob.size.toLocaleString()} bytes`,
      Estimate: estimateCost(provider, textEl.value.length),
    },
  });
};

generateBtn.addEventListener('click', async () => {
  generateBtn.disabled = true;
  try {
    await generateFor(providerEl.value);
  } catch (err) {
    setError(err.message);
  }
  generateBtn.disabled = false;
});

compareBtn.addEventListener('click', async () => {
  compareBtn.disabled = true;
  for (const provider of ['gemini', 'openai', 'elevenlabs']) {
    try {
      await generateFor(provider);
    } catch (err) {
      setError(err.message);
    }
  }
  compareBtn.disabled = false;
});

sampleBtn.addEventListener('click', () => {
  textEl.value = 'Today we are studying active recall and spaced repetition. Active recall means testing yourself before checking the answer. Spaced repetition means reviewing the same concept at increasing intervals so the memory becomes stronger over time.';
  updateCount();
});

textEl.addEventListener('input', updateCount);
updateCount();
