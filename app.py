"""Price From Photo: upload a photo of an item, get an AI price estimate.

UI: Streamlit. AI: Google Gemini Flash (via the google-genai SDK).
"""

import io
import os
import time
from typing import Literal, Optional

import streamlit as st
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field, ValidationError

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------
DEFAULT_MODEL = "gemini-3.6-flash"  # override with GEMINI_MODEL in secrets/env
MAX_IMAGE_SIDE = 1568               # px; larger photos are downscaled
MAX_UPLOAD_MB = 10
COOLDOWN_SECONDS = 5                # minimum gap between requests per session
CURRENCIES = ["USD", "EUR", "GBP", "CAD", "AUD", "INR", "JPY"]

PROMPT_TEMPLATE = """You are a pricing assistant. Look at the photo and estimate the
typical current market price of the main item shown, in {currency}.

Rules:
- Identify the single main item (brand/model if visible, otherwise a clear description).
- Give a realistic range for the item in its visible condition, and a most likely price.
- If the photo does not show a priceable item (for example it is blank, blurry,
  a screenshot of text, or mainly a person), set is_priceable to false, explain in
  reasoning, and set all prices to 0.
- Never guess private information about a person. Do not price people.
- Be honest about uncertainty: use confidence "low" when you cannot identify the
  exact model or condition.
- reasoning: 1-3 sentences on what drives the price.
- tips: 1-3 short, practical tips (for example how to get a more accurate price).
"""


class PriceEstimate(BaseModel):
    is_priceable: bool = Field(description="False if no priceable item is visible")
    item_name: str = ""
    category: str = ""
    condition: str = ""
    price_low: float = 0
    price_typical: float = 0
    price_high: float = 0
    confidence: Literal["low", "medium", "high"] = "low"
    reasoning: str = ""
    tips: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Core logic (no Streamlit calls, so it is easy to test)
# --------------------------------------------------------------------------
def prepare_image(raw: bytes) -> bytes:
    """Validate, fix rotation, downscale, and re-encode as JPEG bytes."""
    if len(raw) > MAX_UPLOAD_MB * 1024 * 1024:
        raise ValueError(f"Image is larger than {MAX_UPLOAD_MB} MB.")
    try:
        img = Image.open(io.BytesIO(raw))
        img = ImageOps.exif_transpose(img)
        img = img.convert("RGB")
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("That file could not be read as an image.") from exc
    img.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=90)
    return out.getvalue()


def parse_estimate(text: Optional[str]) -> PriceEstimate:
    """Parse the model's JSON reply into a validated PriceEstimate."""
    if not text or not text.strip():
        raise ValueError("The model returned an empty response.")
    cleaned = text.strip()
    if cleaned.startswith("```"):  # tolerate accidental code fences
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
    try:
        est = PriceEstimate.model_validate_json(cleaned.strip())
    except ValidationError as exc:
        raise ValueError("The model returned an unexpected format.") from exc
    # Keep low <= typical <= high even if the model gets them out of order.
    low, typ, high = sorted([est.price_low, est.price_typical, est.price_high])
    est.price_low, est.price_typical, est.price_high = low, typ, high
    return est


def estimate_price(client, model: str, image_jpeg: bytes, currency: str) -> PriceEstimate:
    """Send the image to Gemini and return a structured estimate."""
    from google.genai import types  # imported here so tests can stub it

    response = client.models.generate_content(
        model=model,
        contents=[
            types.Part.from_bytes(data=image_jpeg, mime_type="image/jpeg"),
            PROMPT_TEMPLATE.format(currency=currency),
        ],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=PriceEstimate,
        ),
    )
    return parse_estimate(response.text)


# --------------------------------------------------------------------------
# Streamlit helpers
# --------------------------------------------------------------------------
def get_secret(name: str, default: Optional[str] = None) -> Optional[str]:
    """Read from Streamlit secrets first, then environment variables."""
    try:
        value = st.secrets[name]
        if value:
            return str(value)
    except Exception:  # no secrets file, or key missing
        pass
    return os.environ.get(name, default)


@st.cache_resource
def get_client(api_key: str):
    from google import genai

    return genai.Client(api_key=api_key)


def money(amount: float, currency: str) -> str:
    return f"{amount:,.0f} {currency}" if currency == "JPY" else f"{amount:,.2f} {currency}"


# --------------------------------------------------------------------------
# UI
# --------------------------------------------------------------------------
def main() -> None:
    st.set_page_config(page_title="Price From Photo", page_icon="🏷️", layout="centered")
    st.title("🏷️ Price From Photo")
    st.write("Add a photo of an item and get an estimated market price in seconds.")

    api_key = get_secret("GEMINI_API_KEY")
    model = get_secret("GEMINI_MODEL", DEFAULT_MODEL)
    if not api_key:
        st.error(
            "No API key found. Add `GEMINI_API_KEY` to `.streamlit/secrets.toml` "
            "(locally) or to your app's Secrets settings (Streamlit Cloud)."
        )
        st.stop()

    currency = st.selectbox("Currency", CURRENCIES, index=0)

    tab_upload, tab_camera = st.tabs(["Upload a photo", "Take a photo"])
    with tab_upload:
        uploaded = st.file_uploader(
            "Drag and drop or browse for an image",
            type=["png", "jpg", "jpeg", "webp"],
        )
    with tab_camera:
        camera = st.camera_input("Point your camera at the item")

    source = uploaded or camera
    if source is None:
        st.info("Add a photo to get started.")
        return

    raw = source.getvalue()
    try:
        image_jpeg = prepare_image(raw)
    except ValueError as exc:
        st.error(str(exc))
        return

    st.image(image_jpeg, caption="Your photo")

    if st.button("Get my price", type="primary"):
        last = st.session_state.get("last_request", 0.0)
        wait = COOLDOWN_SECONDS - (time.time() - last)
        if wait > 0:
            st.warning(f"Please wait {wait:.0f} more second(s) before trying again.")
            return
        st.session_state["last_request"] = time.time()

        with st.spinner("Estimating price..."):
            try:
                result = estimate_price(get_client(api_key), model, image_jpeg, currency)
            except ValueError as exc:
                st.error(str(exc))
                return
            except Exception as exc:  # network, quota, bad key, model name...
                st.error(f"Something went wrong calling the AI model: {exc}")
                return
        st.session_state["result"] = (result, currency)

    if "result" in st.session_state:
        show_result(*st.session_state["result"])


def show_result(result: PriceEstimate, currency: str) -> None:
    if not result.is_priceable:
        st.warning(result.reasoning or "I couldn't find an item to price in this photo.")
        return

    st.subheader(result.item_name or "Item")
    meta = [x for x in (result.category, result.condition) if x]
    if meta:
        st.caption(" | ".join(meta))

    st.metric("Estimated price", money(result.price_typical, currency))
    col_low, col_high = st.columns(2)
    col_low.metric("Low", money(result.price_low, currency))
    col_high.metric("High", money(result.price_high, currency))
    st.write(f"**Confidence:** {result.confidence}")

    if result.reasoning:
        st.write(result.reasoning)
    for tip in result.tips:
        st.markdown(f"- {tip}")
    st.caption("AI estimates are approximate and not a professional appraisal.")


if __name__ == "__main__":
    main()
          
