import io
import time
import base64
import requests
import streamlit as st

API_URL = "https://cix08u1fwd.execute-api.us-east-1.amazonaws.com/default/fnPolly"

st.set_page_config(page_title="Transcribe & TTS", layout="wide")

try:
    from audio_recorder_streamlit import audio_recorder
    HAS_RECORDER = True
except Exception:
    HAS_RECORDER = False
def api_post_json(payload: dict) -> dict:
    r = requests.post(API_URL, json=payload, timeout=60)
    r.raise_for_status()
    return r.json()

def upload_to_presigned(url: str, data: bytes, content_type: str):
    r = requests.put(url, data=data, headers={"Content-Type": content_type}, timeout=120)
    r.raise_for_status()

def poll_transcription(job_name: str, max_secs: int = 120, interval: float = 2.0) -> dict:
    start = time.time()
    with st.spinner("Transcribiendo..."):
        while True:
            resp = api_post_json({"action": "transcribe_result", "job_name": job_name})
            status = resp.get("status")
            if status == "COMPLETED":
                return resp
            if status in ("FAILED", "NOT_FOUND"):
                return resp
            if time.time() - start > max_secs:
                return {"status": "TIMEOUT", "job_name": job_name}
            time.sleep(interval)

def guess_mime(filename: str) -> str:
    fn = filename.lower()
    if fn.endswith(".wav"): return "audio/wav"
    if fn.endswith(".mp3"): return "audio/mpeg"
    if fn.endswith(".ogg") or fn.endswith(".opus"): return "audio/ogg"
    if fn.endswith(".flac"): return "audio/flac"
    if fn.endswith(".amr"): return "audio/amr"
    if fn.endswith(".mp4"): return "audio/mp4"
    return "application/octet-stream"
col_left, col_right = st.columns(2, gap="large")

with col_left:
    st.subheader("🎙️ Audio → Texto (Transcribe)")
    
    option = st.radio("Elige una opción:", ["Grabar audio", "Subir archivo de audio"])
    
    audio_bytes = None
    filename = None
    mime = None

    if option == "Grabar audio":
        if HAS_RECORDER:
            st.caption("Graba tu audio y luego presiona Transcribir")
            recorded = audio_recorder(pause_threshold=2.0, sample_rate=44100)
            if recorded:
                audio_bytes = recorded
                filename = "grabacion.wav"
                mime = "audio/wav"
                st.audio(audio_bytes, format=mime)
        else:
            st.warning("La funcionalidad de grabación no está disponible. Instala 'audio-recorder-streamlit'.")
    
    elif option == "Subir archivo de audio":
        st.caption("Sube un archivo de audio (WAV/MP3/OGG/OPUS...)")
        up = st.file_uploader("Archivo de audio", type=["wav","mp3","ogg","opus","flac","amr","mp4"])
        if up:
            audio_bytes = up.read()
            filename = up.name
            mime = up.type or guess_mime(up.name)
            st.audio(audio_bytes, format=mime)

    if st.button("Transcribir", type="primary", disabled=audio_bytes is None):
        try:
            if not mime:
                mime = guess_mime(filename or "audio.wav")

            presign = api_post_json({
                "action": "create_upload_url",
                "filename": filename or "grabacion.wav",
                "content_type": mime
            })
            upload_url = presign["upload_url"]
            s3_key = presign["s3_key"]       

            upload_to_presigned(upload_url, audio_bytes, mime)

            start = api_post_json({
                "action": "transcribe_start",
                "s3_key": s3_key
            })
            job_name = start["job_name"]

            result = poll_transcription(job_name)
            status = result.get("status")

            if status == "COMPLETED":
                st.success("Transcripción lista.")
                st.text_area("Texto transcrito", result.get("transcript",""), height=240, key=f"trans_{job_name}")
            elif status == "TIMEOUT":
                st.warning("Se agotó el tiempo de espera. Intenta consultar nuevamente en unos segundos.")
            elif status == "FAILED":
                st.error(f"Transcripción falló: {result.get('reason','')}")
            elif status == "NOT_FOUND":
                st.error("Job no encontrado. Vuelve a intentar la subida.")
            else:
                st.info(f"Estado: {status}")
        except requests.HTTPError as e:
            st.error(f"Error HTTP: {e.response.status_code} - {e.response.text}")
        except Exception as e:
            st.error(f"Error: {e}")

with col_right:
    st.subheader("🗣️ Texto → Audio (Polly)")
    tts_text = st.text_area("Escribe el texto a convertir", "", height=200)
    
    voice = st.radio("Selecciona una voz:", ["Lucia", "Conchita", "Mia", "Miguel", "Penelope"], index=0, horizontal=True, key="voice_radio")
    
    engine = st.radio("Selecciona el motor:", ["neural", "standard"], index=0, horizontal=True, key="engine_radio")
    
    fmt = st.radio("Selecciona el formato:", ["mp3", "ogg_vorbis"], index=0, horizontal=True, key="format_radio")

    if st.button("Generar audio"):
        if not tts_text.strip():
            st.warning("Escribe un texto primero.")
        else:
            try:
                resp = api_post_json({
                    "action": "polly_synthesize",
                    "text": tts_text,
                    "voice_id": voice,
                    "engine": engine,
                    "format": fmt
                })
                url = resp.get("audio_url")
                if not url:
                    st.error("No se recibió URL de audio.")
                else:
                    st.success("Audio generado.")
                    audio_bytes = requests.get(url, timeout=120).content
                    mime = "audio/mpeg" if fmt == "mp3" else ("audio/ogg" if fmt == "ogg_vorbis" else "audio/wav")
                    st.audio(audio_bytes, format=mime)
            except requests.HTTPError as e:
                st.error(f"Error HTTP: {e.response.status_code} - {e.response.text}")
            except Exception as e:
                st.error(f"Error: {e}")