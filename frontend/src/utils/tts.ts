/**
 * SARATHI Voice — streams Microsoft Neural TTS audio from the pdsaibot backend.
 * Voices used (all female, all Neural quality):
 *   English → en-IN-NeerjaNeural
 *   Hindi   → hi-IN-SwaraNeural
 *   Tamil   → ta-IN-PallaviNeural
 *   Telugu  → te-IN-ShrutiNeural
 *   Kannada → kn-IN-SapnaNeural
 */

const TTS_URL = "http://localhost:8004/api/bot/tts";

let _currentAudio: HTMLAudioElement | null = null;

export async function speak(
  text: string,
  language: string,
  onStart?: () => void,
  onEnd?: () => void,
): Promise<void> {
  stopSpeech(); // cancel any playing audio first

  try {
    const res = await fetch(TTS_URL, {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify({ text, language }),
    });

    if (!res.ok) {
      console.warn("TTS backend error:", res.status, await res.text());
      onEnd?.();
      return;
    }

    const blob  = await res.blob();
    const url   = URL.createObjectURL(blob);
    const audio = new Audio(url);

    _currentAudio = audio;

    audio.onplay  = () => onStart?.();
    audio.onended = () => { URL.revokeObjectURL(url); _currentAudio = null; onEnd?.(); };
    audio.onerror = () => { URL.revokeObjectURL(url); _currentAudio = null; onEnd?.(); };

    await audio.play();
  } catch (err) {
    console.warn("TTS speak error:", err);
    onEnd?.();
  }
}

export function stopSpeech(): void {
  if (_currentAudio) {
    _currentAudio.pause();
    _currentAudio = null;
  }
}

export function isSpeaking(): boolean {
  return _currentAudio !== null && !_currentAudio.paused;
}
