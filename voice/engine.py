"""
Open-PY v5.1 — Voice Engine
STT (faster-whisper) + TTS (piper-tts)

Suporta múltiplos idiomas. Default: pt-BR.
Projetado para VMs com 8GB RAM — modelos small/base.
"""

import asyncio
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from shared.logger import get_logger

log = get_logger("voice")

# Diretório dos modelos Piper
PIPER_MODELS_DIR = Path(os.environ.get("OPENPY_DIR", "/opt/open-py")) / "data" / "piper_models"

# Mapa de vozes Piper por idioma (model_name → download URL base)
PIPER_VOICES: dict[str, dict[str, str]] = {
    "pt-BR": {
        "model": "pt_BR-faber-medium",
        "url": "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/pt/pt_BR/faber/medium/pt_BR-faber-medium.onnx",
        "config_url": "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/pt/pt_BR/faber/medium/pt_BR-faber-medium.onnx.json",
    },
    "en-US": {
        "model": "en_US-amy-medium",
        "url": "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/amy/medium/en_US-amy-medium.onnx",
        "config_url": "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/amy/medium/en_US-amy-medium.onnx.json",
    },
    "es-ES": {
        "model": "es_ES-davefx-medium",
        "url": "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/es/es_ES/davefx/medium/es_ES-davefx-medium.onnx",
        "config_url": "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/es/es_ES/davefx/medium/es_ES-davefx-medium.onnx.json",
    },
}


class VoiceEngine:
    """
    Unifica STT (faster-whisper) + TTS (piper-tts).

    STT: faster-whisper com modelo "base" (int8, CPU)
    TTS: piper-tts com modelos ONNX por idioma
    """

    def __init__(
        self,
        whisper_model: str = "base",
        whisper_device: str = "auto",
        whisper_compute: str = "auto",
        default_language: str = "pt-BR",
        tts_enabled: bool = True,
        stt_enabled: bool = True,
    ):
        self.whisper_model_name = whisper_model
        self.whisper_device = whisper_device
        self.whisper_compute = whisper_compute
        self.default_language = default_language
        self.tts_enabled = tts_enabled
        self.stt_enabled = stt_enabled

        self._whisper_model = None
        self._piper_voices: dict[str, object] = {}  # lang → PiperVoice

        self._stt_available = False
        self._tts_available = False

    async def initialize(self):
        """Carrega modelos de forma assíncrona (não bloqueia event loop)."""
        loop = asyncio.get_event_loop()

        # STT: faster-whisper
        if self.stt_enabled:
            try:
                self._whisper_model = await loop.run_in_executor(None, self._load_whisper)
                self._stt_available = True
                log.info("✅ STT pronto (faster-whisper)",
                         model=self.whisper_model_name,
                         device=self.whisper_device)
            except Exception as e:
                log.warning("⚠️ STT indisponível", error=str(e))

        # TTS: piper-tts
        if self.tts_enabled:
            try:
                await self._ensure_piper_model(self.default_language)
                voice = await loop.run_in_executor(
                    None, self._load_piper_voice, self.default_language
                )
                if voice:
                    self._piper_voices[self.default_language] = voice
                    self._tts_available = True
                    log.info("✅ TTS pronto (piper)",
                             language=self.default_language,
                             model=PIPER_VOICES.get(self.default_language, {}).get("model", "?"))
            except Exception as e:
                log.warning("⚠️ TTS indisponível", error=str(e))

    def _load_whisper(self):
        """Carrega modelo faster-whisper (blocking — rodar em executor)."""
        from faster_whisper import WhisperModel

        # Auto-detect device/compute
        device = self.whisper_device
        compute_type = self.whisper_compute

        if device == "auto":
            try:
                import torch
                device = "cuda" if torch.cuda.is_available() else "cpu"
            except ImportError:
                device = "cpu"

        if compute_type == "auto":
            compute_type = "float16" if device == "cuda" else "int8"

        self.whisper_device = device
        self.whisper_compute = compute_type

        return WhisperModel(
            self.whisper_model_name,
            device=device,
            compute_type=compute_type,
        )

    def _load_piper_voice(self, language: str):
        """Carrega voz Piper (blocking)."""
        voice_info = PIPER_VOICES.get(language)
        if not voice_info:
            log.warning(f"Voz Piper não configurada para '{language}'")
            return None

        model_path = PIPER_MODELS_DIR / f"{voice_info['model']}.onnx"
        config_path = PIPER_MODELS_DIR / f"{voice_info['model']}.onnx.json"

        if not model_path.exists() or not config_path.exists():
            log.warning(f"Modelo Piper não encontrado: {model_path}")
            return None

        try:
            from piper import PiperVoice
            return PiperVoice.load(str(model_path), config_path=str(config_path))
        except Exception as e:
            log.error("Erro carregando Piper", error=str(e))
            return None

    async def _ensure_piper_model(self, language: str):
        """Faz download do modelo Piper se não existir."""
        voice_info = PIPER_VOICES.get(language)
        if not voice_info:
            return

        PIPER_MODELS_DIR.mkdir(parents=True, exist_ok=True)
        model_path = PIPER_MODELS_DIR / f"{voice_info['model']}.onnx"
        config_path = PIPER_MODELS_DIR / f"{voice_info['model']}.onnx.json"

        if model_path.exists() and config_path.exists():
            return  # Já baixado

        log.info("📥 Baixando modelo Piper TTS...", language=language,
                 model=voice_info["model"])

        loop = asyncio.get_event_loop()
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                # Download modelo .onnx
                async with session.get(voice_info["url"]) as resp:
                    if resp.status == 200:
                        data = await resp.read()
                        await loop.run_in_executor(
                            None, lambda: model_path.write_bytes(data)
                        )
                    else:
                        log.error("❌ Falha no download do modelo Piper",
                                  status=resp.status)
                        return

                # Download config .json
                async with session.get(voice_info["config_url"]) as resp:
                    if resp.status == 200:
                        data = await resp.read()
                        await loop.run_in_executor(
                            None, lambda: config_path.write_bytes(data)
                        )

            log.info("✅ Modelo Piper baixado", model=voice_info["model"])
        except Exception as e:
            log.error("❌ Erro baixando modelo Piper", error=str(e))

    # ============================================
    # STT — Speech to Text (faster-whisper)
    # ============================================

    async def transcribe(
        self,
        audio_path: str,
        language: Optional[str] = None,
    ) -> dict[str, str | float]:
        """
        Transcreve áudio para texto.

        Args:
            audio_path: Caminho do arquivo de áudio
            language: Código ISO do idioma (None = auto-detect)

        Returns:
            {"text": "transcrição", "language": "pt", "confidence": 0.95, "duration": 3.2}
        """
        if not self._stt_available or not self._whisper_model:
            return {"text": "", "language": "", "confidence": 0.0,
                    "error": "STT não disponível"}

        loop = asyncio.get_event_loop()

        try:
            result = await loop.run_in_executor(
                None, self._transcribe_sync, audio_path, language
            )
            log.info("🎤 Transcrição concluída",
                     chars=len(result["text"]),
                     language=result["language"],
                     confidence=f"{result['confidence']:.2f}")
            return result
        except Exception as e:
            log.error("❌ Erro na transcrição", error=str(e))
            return {"text": "", "language": "", "confidence": 0.0,
                    "error": str(e)}

    def _transcribe_sync(
        self,
        audio_path: str,
        language: Optional[str],
    ) -> dict[str, str | float]:
        """Transcrição síncrona (roda em executor)."""
        # Converter código de idioma se necessário (pt-BR → pt)
        whisper_lang = None
        if language:
            whisper_lang = language.split("-")[0].lower()

        segments, info = self._whisper_model.transcribe(
            audio_path,
            beam_size=5,
            language=whisper_lang,
            vad_filter=True,  # Filtra silêncio — reduz alucinação
            vad_parameters=dict(min_silence_duration_ms=500),
        )

        # Concatenar todos os segmentos
        full_text = ""
        total_duration = 0.0
        for segment in segments:
            full_text += segment.text
            total_duration = max(total_duration, segment.end)

        return {
            "text": full_text.strip(),
            "language": info.language,
            "confidence": info.language_probability,
            "duration": round(total_duration, 2),
        }

    # ============================================
    # TTS — Text to Speech (piper-tts)
    # ============================================

    async def synthesize(
        self,
        text: str,
        language: Optional[str] = None,
        output_format: str = "ogg",
    ) -> Optional[str]:
        """
        Sintetiza texto em áudio.

        Args:
            text: Texto para sintetizar
            language: Código do idioma (None = default)
            output_format: "ogg" (Telegram voice), "wav", "mp3"

        Returns:
            Caminho do arquivo de áudio gerado, ou None em caso de erro
        """
        if not self._tts_available:
            log.warning("TTS não disponível")
            return None

        lang = language or self.default_language

        # Carregar voz sob demanda se idioma diferente do default
        if lang not in self._piper_voices:
            await self._ensure_piper_model(lang)
            loop = asyncio.get_event_loop()
            voice = await loop.run_in_executor(None, self._load_piper_voice, lang)
            if voice:
                self._piper_voices[lang] = voice
            else:
                log.warning(f"Voz não disponível para '{lang}', usando default")
                lang = self.default_language

        voice = self._piper_voices.get(lang)
        if not voice:
            return None

        loop = asyncio.get_event_loop()
        try:
            wav_path = await loop.run_in_executor(
                None, self._synthesize_sync, voice, text
            )

            if output_format == "wav":
                return wav_path

            # Converter para ogg/opus (Telegram voice) ou mp3
            output_path = wav_path.replace(".wav", f".{output_format}")
            converted = await self._convert_audio(wav_path, output_path, output_format)

            # Limpar wav temporário se conversão ok
            if converted and converted != wav_path:
                try:
                    os.unlink(wav_path)
                except OSError:
                    pass

            log.info("🔊 TTS concluído", chars=len(text), format=output_format)
            return converted

        except Exception as e:
            log.error("❌ Erro no TTS", error=str(e))
            return None

    def _synthesize_sync(self, voice, text: str) -> str:
        """Síntese síncrona (roda em executor)."""
        import wave

        # Limpar texto — remover markdown, emojis excessivos, etc.
        clean_text = self._clean_text_for_tts(text)
        if not clean_text:
            clean_text = text[:500]  # Fallback

        tmp_dir = Path(os.environ.get("OPENPY_DIR", "/opt/open-py")) / "data" / "media"
        tmp_dir.mkdir(parents=True, exist_ok=True)

        wav_path = str(tmp_dir / f"tts_{os.getpid()}_{id(text) % 10000}.wav")

        with wave.open(wav_path, "wb") as wav_file:
            voice.synthesize(clean_text, wav_file)

        return wav_path

    @staticmethod
    def _clean_text_for_tts(text: str) -> str:
        """Remove formatação markdown e elementos indesejados para TTS."""
        import re

        cleaned = text

        # Remover blocos de código
        cleaned = re.sub(r"```[\s\S]*?```", " código omitido ", cleaned)
        cleaned = re.sub(r"`[^`]+`", "", cleaned)

        # Remover markdown formatting
        cleaned = re.sub(r"\*\*(.+?)\*\*", r"\1", cleaned)  # bold
        cleaned = re.sub(r"\*(.+?)\*", r"\1", cleaned)      # italic
        cleaned = re.sub(r"__(.+?)__", r"\1", cleaned)      # underline
        cleaned = re.sub(r"~~(.+?)~~", r"\1", cleaned)      # strikethrough

        # Remover headers markdown
        cleaned = re.sub(r"^#{1,6}\s+", "", cleaned, flags=re.MULTILINE)

        # Remover links markdown
        cleaned = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", cleaned)

        # Remover URLs
        cleaned = re.sub(r"https?://\S+", " link ", cleaned)

        # Remover emojis excessivos (manter alguns)
        cleaned = re.sub(r"([\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF])\1+", r"\1", cleaned)

        # Limpar espaços múltiplos
        cleaned = re.sub(r"\s+", " ", cleaned).strip()

        # Limitar tamanho (Piper fica lento com textos muito longos)
        if len(cleaned) > 2000:
            cleaned = cleaned[:2000] + "... texto truncado."

        return cleaned

    async def _convert_audio(
        self,
        input_path: str,
        output_path: str,
        output_format: str,
    ) -> Optional[str]:
        """Converte áudio via ffmpeg."""
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            log.warning("⚠️ ffmpeg não encontrado — retornando WAV")
            return input_path

        cmd = [ffmpeg, "-y", "-i", input_path]

        if output_format == "ogg":
            cmd.extend(["-acodec", "libopus", "-b:a", "64k", "-vbr", "on"])
        elif output_format == "mp3":
            cmd.extend(["-acodec", "libmp3lame", "-b:a", "96k"])

        cmd.append(output_path)

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)

            if proc.returncode == 0 and os.path.exists(output_path):
                return output_path
            else:
                log.warning("ffmpeg falhou", stderr=stderr.decode()[-200:])
                return input_path
        except asyncio.TimeoutError:
            log.warning("ffmpeg timeout")
            return input_path

    # ============================================
    # STATUS
    # ============================================

    def status(self) -> dict:
        """Retorna status dos engines."""
        return {
            "stt_available": self._stt_available,
            "stt_model": self.whisper_model_name if self._stt_available else None,
            "stt_device": self.whisper_device if self._stt_available else None,
            "tts_available": self._tts_available,
            "tts_voices_loaded": list(self._piper_voices.keys()),
            "default_language": self.default_language,
        }
