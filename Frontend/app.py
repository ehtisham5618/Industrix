"""Streamlit presentation for existing FastAPI inference and stream workers."""
import io
import os
import sys
from pathlib import Path

import requests
import streamlit as st
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from Frontend.api_client import APIClient
from Frontend.live_component import live_console
from Frontend.incidents import incident_history

st.set_page_config(page_title="Industrial Vision Console", layout="wide",initial_sidebar_state='collapsed' if os.getenv('IFE_UI3_DEMO')=='true' else 'auto')
st.title("Industrial Vision Console")
if os.getenv('IFE_UI3_DEMO')=='true':
    st.caption('Vision-Driven Industrial Safety & Quality Inspection Engine | Sprint 4 CPU-Ready Demo')
    st.info('LOCAL / CPU / OFFLINE-GUARDED DEMO: cameras 01/02 repeat textile/fire dataset images; camera 03 plays a worker video. Fire starts after 75 seconds standby. Real inference, tracking and confirmation; simulated safety shutdown only.')
st.caption("Hangzhou 2026 POC · Textile quality and factory safety")
backend_url = st.sidebar.text_input("FastAPI Backend URL", os.getenv('BACKEND_URL','http://127.0.0.1:8000'))
st.sidebar.caption("Run FastAPI separately. The console uses existing CPU stream workers.")
try:
    client=APIClient(backend_url)
except ValueError as exc:
    st.error(str(exc)); st.stop()
monitor_tab, image_tab = st.tabs(["Live Monitor", "Image Inference"])
with monitor_tab:
    left,right,detail=st.columns([1,1,4])
    if left.button("Start three feeds",type='primary'):
        try:
            result=client.request('POST','/streams/start',params={'streams':3,'engine':'openvino','imgsz':640,'device':'cpu','persist_frames':15})
            st.success("Three feeds started using the verified OpenVINO INT8 CPU artifact.")
        except requests.RequestException as exc:
            st.error(f"Unable to start streams: {exc}")
    if right.button("Stop feeds"):
        try:
            client.request('POST','/streams/stop');st.info("Streams stopped.")
        except requests.RequestException as exc:
            st.error(f"Unable to stop streams: {exc}")
    detail.caption("Ring: 15 raw frames · Every fourth raw frame evaluated · 15 evaluated observations to confirm")
    live_console(client.base_url)

with image_tab:
    st.write("Upload a textile/fabric image to detect and visualize fabric defects.")
    uploaded_file = st.file_uploader("Upload an image (JPG, JPEG, PNG)", type=["jpg", "jpeg", "png"])

    if uploaded_file is not None:
        try:
            image_bytes = uploaded_file.read()
            image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        except Exception:
            st.error("Unable to read the uploaded image. Please upload a valid JPG/PNG file.")
            uploaded_file = None

    if uploaded_file is not None:
        cols = st.columns([1, 1])
        with cols[0]:
            st.image(image, caption="Original image", width="stretch")
            st.write(f"Dimensions: {image.width} x {image.height} pixels")

        detect = st.button("Detect Defects")

        if detect:
            predict_url = backend_url.rstrip("/") + "/predict"
            with st.spinner("Sending image to FastAPI for inference..."):
                try:
                    files = {"file": (uploaded_file.name, image_bytes, uploaded_file.type or "image/jpeg")}
                    resp = requests.post(predict_url, files=files, timeout=(5, 30))
                except requests.ConnectionError:
                    st.error("FastAPI backend is unavailable. Please start the backend and try again.")
                    st.stop()
                except requests.Timeout:
                    st.error("Request to backend timed out. Try again or increase timeout.")
                    st.stop()
                except requests.RequestException as e:
                    st.error(f"Request failed: {e}")
                    st.stop()

            if resp.status_code != 200:
                st.error(f"Backend returned status code {resp.status_code}")
            else:
                try:
                    data = resp.json()
                except Exception:
                    st.error("Backend returned an unexpected response (not valid JSON).")
                    st.stop()

                detections = data.get("detections", [])

                if not detections:
                    st.success("No defects detected.")
                else:
                    annotated = image.copy()
                    draw = ImageDraw.Draw(annotated)
                    try:
                        font = ImageFont.load_default()
                    except Exception:
                        font = None

                    for det in detections:
                        coords = det.get("coordinates", {})
                        x1 = coords.get("x1")
                        y1 = coords.get("y1")
                        x2 = coords.get("x2")
                        y2 = coords.get("y2")
                        cls = det.get("class_name", str(det.get("class_id", "?")))
                        conf = det.get("confidence", 0.0)

                        if None in (x1, y1, x2, y2):
                            continue

                        try:
                            box = [float(x1), float(y1), float(x2), float(y2)]
                        except Exception:
                            continue

                        draw.rectangle(box, outline="red", width=3)
                        label = f"{cls} - {round(float(conf) * 100, 1)}%"
                        text_bbox = draw.textbbox((0, 0), label, font=font) if font else (0, 0, 0, 0)
                        text_width = text_bbox[2] - text_bbox[0]
                        text_height = text_bbox[3] - text_bbox[1]
                        text_bg = [box[0], box[1] - text_height - 4, box[0] + text_width + 4, box[1]]
                        draw.rectangle(text_bg, fill="red")
                        draw.text((box[0] + 2, box[1] - text_height - 2), label, fill="white", font=font)

                    with cols[1]:
                        st.image(annotated, caption="Annotated result", width="stretch")

                    st.subheader("Detection Results")
                    st.write(f"Defects detected: {len(detections)}")
                    rows = []
                    for det in detections:
                        cls = det.get("class_name", str(det.get("class_id", "?")))
                        conf = det.get("confidence", 0.0)
                        rows.append({"Defect": cls, "Confidence": f"{round(float(conf) * 100, 1)}%"})

                    st.table(rows)

# Render the independent export fragment after initial image-upload controls
# have initialized, so its first visible button can receive an immediate rerun.
with monitor_tab:
    incident_history(client)
    from Frontend.qci3 import quality_alarm_status
    quality_alarm_status(client)
    from Frontend.qci4 import edge_health_status
    edge_health_status(client)
