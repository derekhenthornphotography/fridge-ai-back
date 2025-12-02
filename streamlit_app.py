import io
from typing import List, Dict, Any

import requests
import streamlit as st

# === Konfiguration ===

BACKEND_BASE_URL = "https://fridge-ai-back.onrender.com"
BACKEND_ANALYZE_URL = f"https://fridge-ai-back.onrender.com/analyze-image/"
BACKEND_SUGGEST_URL = f"https://fridge-ai-back.onrender.com/ai-recipes/"
CONFIDENCE_THRESHOLD = 0.05  # nur für Anzeige/Filter


def call_backend_analyze(image_bytes: bytes, content_type: str) -> List[Dict[str, Any]]:
    """
    Schickt das Bild an dein FastAPI-Backend (/analyze-image/)
    und erhält die erkannte Liste der Lebensmittel zurück.
    """
    files = {
        "file": ("upload.jpg", io.BytesIO(image_bytes), content_type or "image/jpeg")
    }

    resp = requests.post(BACKEND_ANALYZE_URL, files=files)
    resp.raise_for_status()
    data = resp.json()

    items = data.get("items", [])

    # Normalisieren und sortieren
    norm_items = [
        {
            "name": str(it.get("name", "")).lower(),
            "score": float(it.get("score", 0.0)),
        }
        for it in items
        if it.get("name")
    ]

    norm_items = sorted(norm_items, key=lambda x: x["score"], reverse=True)
    return norm_items


def call_backend_recipes(detected_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Schickt die erkannten Lebensmittel an dein Backend (/suggest-recipes/)
    und erhält Rezeptvorschläge zurück.
    """
    payload = {
        "items": [
            {
                "name": item["name"],
                "score": float(item["score"]),
            }
            for item in detected_items
        ]
    }

    resp = requests.post(BACKEND_SUGGEST_URL, json=payload)
    resp.raise_for_status()
    data = resp.json()

    suggestions = data.get("suggestions", [])
    return suggestions


# === Streamlit UI ===

st.set_page_config(
    page_title="KitchenWise – Your cooking companion",
    page_icon="🍳",
)

st.title("KitchenWise")
st.subheader("Your cooking companion for everyday meals.")

st.write(
    """
Upload a photo of your ingredients and let KitchenWise:

- **Recognise what’s there** using food image detection  
- **Suggest practical recipes** based on what you already have  
- **Create a focused shopping list** only for what’s missing  

This is an early **beta version** – results may not always be perfect.
Your feedback helps to improve the app.
"""
)

st.markdown("### 1. Upload a fridge or ingredient photo")

uploaded_file = st.file_uploader(
    "Choose a photo (JPG/PNG/WebP)", type=["jpg", "jpeg", "png", "webp"]
)

if uploaded_file is not None:
    st.image(uploaded_file, caption="Uploaded image", use_container_width=True)
    image_bytes = uploaded_file.read()
    content_type = uploaded_file.type or "image/jpeg"

    st.markdown("### 2. Analyse ingredients and get recipes")

    if st.button("Analyse image"):
        with st.spinner("Sending image to your backend..."):
            try:
                detected_items = call_backend_analyze(image_bytes, content_type)
            except requests.HTTPError as e:
                st.error(f"HTTP error from backend (/analyze-image/): {e.response.text}")
            except Exception as e:
                st.error(f"Error during analysis: {e}")
            else:
                if not detected_items:
                    st.warning("No relevant food items detected.")
                else:
                    # 1. Show raw detection results
                    st.subheader("Detected ingredients")
                    for item in detected_items:
                        if item["score"] < CONFIDENCE_THRESHOLD:
                            continue
                        st.write(f"- **{item['name']}** ({item['score']:.2f})")

                    st.markdown("---")
                    st.subheader("Adjust ingredients")

                    detected_names = [it["name"] for it in detected_items]

                    selected_items = st.multiselect(
                        "Which ingredients should be used for recipe suggestions?",
                        options=detected_names,
                        default=detected_names,
                    )

                    extra_items_str = st.text_input(
                        "Optional: Add more ingredients manually (comma-separated)",
                        value="",
                        placeholder="e.g. paprika, feta, tomatoes",
                    )

                    # Build final list of ingredients
                    final_items = []

                    # Selected detected items
                    for it in detected_items:
                        if it["name"] in selected_items:
                            final_items.append(it)

                    # Manually added items (score = 1.0)
                    if extra_items_str.strip():
                        extra_names = [
                            x.strip().lower()
                            for x in extra_items_str.split(",")
                            if x.strip()
                        ]
                        for name in extra_names:
                            final_items.append({"name": name, "score": 1.0})

                    if not final_items:
                        st.info("Please select or add at least one ingredient.")
                        st.stop()  # stop Streamlit run here

                    st.markdown("---")
                    st.subheader("Recipe ideas (from backend)")

                    only_full = st.checkbox(
                        "Show only recipes where all ingredients are available",
                        value=False,
                    )

                    try:
                        suggestions = call_backend_recipes(final_items)
                    except requests.HTTPError as e:
                        st.error(f"HTTP error from backend (/suggest-recipes/): {e.response.text}")
                    except Exception as e:
                        st.error(f"Error while getting recipes: {e}")
                    else:
                        if not suggestions:
                            st.info(
                                "No recipes available for this combination yet in the backend."
                            )
                        else:
                            for s in suggestions:
                                name = s.get("name", "Unnamed recipe")
                                ingredients = s.get("ingredients", [])
                                steps = s.get("steps", [])
                                have = s.get("have", [])
                                missing = s.get("missing", [])
                                total = s.get("total", len(ingredients))

                                if only_full and missing:
                                    continue

                                match_info = f"{len(have)}/{total} ingredients available"

                                st.markdown(f"### 🍽️ {name} ({match_info})")
                                st.write("**Ingredients:** ", ", ".join(ingredients))
                                st.write(
                                    "✅ Already available:",
                                    ", ".join(have) if have else "–",
                                )
                                st.write(
                                    "🛒 To buy:",
                                    ", ".join(missing) if missing else "Nothing, you have everything!",
                                )

                                with st.expander("Show preparation steps"):
                                    for i, step in enumerate(steps, start=1):
                                        st.write(f"{i}. {step}")

st.markdown("---")
st.markdown(
    """
**Beta version**

KitchenWise is under active development.  
If you notice strange detections or recipe suggestions, feel free to send feedback to  
📧 `kitchenwise@ess2studios.com`
"""
)
                                        
