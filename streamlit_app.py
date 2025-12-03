import io
from typing import List, Dict, Any

import requests
import streamlit as st

# === Konfiguration ===

BACKEND_BASE_URL = "https://fridge-ai-back.onrender.com"
BACKEND_ANALYZE_URL = f"https://fridge-ai-back.onrender.com/analyze-image/"
BACKEND_SUGGEST_URL = f"https://fridge-ai-back.onrender.com/ai-recipes/"
BACKEND_SUGGEST_URL = f"https://fridge-ai-back.onrender.com/feedback/"
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


def send_feedback(recipe: Dict[str, Any], liked: bool) -> None:
    """
    Sends simple feedback about a recipe to the backend.
    """
    payload = {
        "recipe_name": recipe.get("name", ""),
        "liked": liked,
        "ingredients": recipe.get("ingredients", []),
        "have": recipe.get("have", []),
        "missing": recipe.get("missing", []),
        "source": "streamlit_v1",
    }

    try:
        resp = requests.post(BACKEND_FEEDBACK_URL, json=payload, timeout=5)
        resp.raise_for_status()
    except Exception as e:
        st.warning(f"Could not send feedback to backend: {e}")


# === Streamlit UI ===

st.set_page_config(page_title="KitchenWise – Food Detector", page_icon="🥕")

st.title("KitchenWise – Lebensmittel erkennen & Rezepte finden")

st.markdown(
    """
KitchenWise works in two steps:

1. We detect ingredients from your photo.
2. We generate simple, realistic recipes with what you have – plus a short shopping list.

**Best results:**

- Place food items clearly on a counter (not hidden in boxes).
- Avoid cluttered full-fridge shots.
- Turn labels towards the camera (for jars, cartons, bottles).
- You can always **add or remove ingredients manually** after detection.
"""
)

st.markdown("### 1. Upload a fridge or ingredient photo")

uploaded_file = st.file_uploader(
    "Bild auswählen", type=["jpg", "jpeg", "png", "webp"]
)

if uploaded_file is not None:
    # Show preview
    st.image(uploaded_file, caption="Uploaded image", use_container_width=True)

    # --- STEP 1: Analyze image ---
    if st.button("Analyze image"):
        with st.spinner("Sending image to your backend..."):
            try:
                image_bytes = uploaded_file.getvalue()
                content_type = uploaded_file.type  # e.g. image/jpeg
                detected_items = call_backend_analyze(image_bytes, content_type)
            except requests.HTTPError as e:
                st.error(f"HTTP error from backend (/analyze-image/): {e.response.text}")
                st.stop()
            except Exception as e:
                st.error(f"Error during analysis: {e}")
                st.stop()

            if not detected_items:
                st.warning("No relevant ingredients detected.")
                st.stop()

            # Filter low-confidence results
            filtered_items = [
                item for item in detected_items
                if item["score"] >= CONFIDENCE_THRESHOLD
            ]

            if not filtered_items:
                st.warning("The model returned only very low-confidence results.")
                st.stop()

            # Store detected items in session for later steps
            st.session_state.detected_items = filtered_items
            # Whenever we re-analyze, clear old recipe suggestions
            st.session_state.pop("suggestions", None)
            st.success(f"Detected {len(filtered_items)} ingredient(s). Adjust them below.")

    # --- STEP 2: Adjust ingredients & generate recipes ---
    if "detected_items" in st.session_state:
        filtered_items = st.session_state.detected_items

        st.subheader("Detected ingredients")
        for item in filtered_items:
            st.write(f"- **{item['name']}** ({item['score']:.2f})")

        st.markdown("---")
        st.subheader("Adjust ingredients before generating recipes")

        all_names = [item["name"] for item in filtered_items]
        default_selection = all_names  # pre-select everything

        selected_names = st.multiselect(
            "Which of these ingredients should KitchenWise use?",
            options=all_names,
            default=default_selection,
            key="ingredient_select",
        )

        extra_ingredients_raw = st.text_input(
            "Add more ingredients manually (comma separated)",
            placeholder="e.g. soy sauce, orange juice, ketchup",
            key="extra_ingredients",
        )

        # Checkbox that also affects already generated recipes
        only_full = st.checkbox(
            "Show only recipes where all ingredients are available",
            value=False,
            key="only_full_recipes",
        )

        # --- Button: Generate recipes ---
        if st.button("Generate recipes"):
            final_items = []

            # Keep only selected detected items
            for item in filtered_items:
                if item["name"] in selected_names:
                    final_items.append(item)

            # Add manually entered ingredients as high-confidence items
            if extra_ingredients_raw.strip():
                extras = [
                    s.strip().lower()
                    for s in extra_ingredients_raw.split(",")
                    if s.strip()
                ]
                for name in extras:
                    final_items.append({"name": name, "score": 1.0})

            if not final_items:
                st.warning("No ingredients selected or added. Please select or add at least one.")
            else:
                try:
                    suggestions = call_backend_recipes(final_items)
                except requests.HTTPError as e:
                    st.error(f"HTTP error from backend (/ai-recipes/): {e.response.text}")
                except Exception as e:
                    st.error(f"Error while generating recipes: {e}")
                else:
                    st.session_state.suggestions = suggestions

       # --- Always show the last generated recipes (if any) ---
suggestions = st.session_state.get("suggestions", [])

if suggestions:
    st.markdown("### Recipe suggestions")

    for idx, s in enumerate(suggestions):
        name = s.get("name", "Unnamed recipe")
        ingredients = s.get("ingredients", [])
        steps = s.get("steps", [])
        have = s.get("have", [])
        missing = s.get("missing", [])
        total = s.get("total", len(ingredients))

        # Apply "only full recipes" filter dynamically
        if st.session_state.get("only_full_recipes") and missing:
            continue

        match_info = f"{len(have)}/{total} ingredients available"

        with st.container():

        # Feedback buttons
        cols = st.columns(2)
        with cols[0]:
            if st.button("👍 Sounds good", key=f"like_{idx}"):
                send_feedback(s, liked=True)
                st.success("Thanks for your feedback!")

        with cols[1]:
            if st.button("👎 Not my taste", key=f"dislike_{idx}"):
                send_feedback(s, liked=False)
                st.info("Got it, thanks for letting us know.")
                    
            st.markdown(f"#### 🍽️ {name}")
            st.caption(match_info)

            # Ingredients as bullet list
            st.markdown("**Ingredients:**")
            if ingredients:
                for ing in ingredients:
                    st.markdown(f"- {ing}")
            else:
                st.markdown("- n/a")

            # Have / missing
            st.markdown(
                "**You already have:** "
                + (", ".join(have) if have else "–")
            )
            st.markdown(
                "**You still need to buy:** "
                + (", ".join(missing) if missing else "Nothing, you’re good!")
            )

            # Steps as numbered list
            with st.expander("Show preparation steps"):
                if steps:
                    for i, step in enumerate(steps, start=1):
                        st.markdown(f"{i}. {step}")
                else:
                    st.write("No steps provided.")

            st.markdown("---")
else:
    st.info("No recipes generated yet. Adjust ingredients and click **Generate recipes**.")

st.markdown("---")
st.markdown(
    """
**Beta version**

KitchenWise is under active development.  
If you notice strange detections or recipe suggestions, feel free to send feedback to  
📧 `kitchenwise@ess2studios.com`
"""
)
                                        
