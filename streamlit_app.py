import io
from typing import List, Dict, Any

import requests
import streamlit as st

# === Konfiguration ===

BACKEND_BASE_URL = "https://fridge-ai-back.onrender.com"
BACKEND_ANALYZE_URL = f"https://fridge-ai-back.onrender.com/analyze-image/"
BACKEND_SUGGEST_URL = f"https://fridge-ai-back.onrender.com/suggest-recipes/"
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

st.set_page_config(page_title="Fridge AI – Food Detector", page_icon="🥕")

st.title("Fridge AI – Lebensmittelerkennung & Rezeptideen")

st.write(
    "Dieses Frontend spricht mit deinem eigenen FastAPI-Backend:\n"
    "- `/analyze-image/` erkennt Lebensmittel auf dem Bild\n"
    "- `/suggest-recipes/` schlägt dir passende Rezepte und Einkaufslisten vor"
)

uploaded_file = st.file_uploader(
    "Bild auswählen", type=["jpg", "jpeg", "png", "webp"]
)

if uploaded_file is not None:
    st.image(uploaded_file, caption="Hochgeladenes Bild", use_column_width=True)
    image_bytes = uploaded_file.read()
    content_type = uploaded_file.type  # z.B. image/jpeg

    if st.button("Bild analysieren"):
        with st.spinner("Schicke Bild an dein Backend..."):
            try:
                detected_items = call_backend_analyze(image_bytes, content_type)
            except requests.HTTPError as e:
                st.error(f"HTTP-Fehler vom Backend (/analyze-image/): {e.response.text}")
            except Exception as e:
                st.error(f"Fehler bei der Analyse: {e}")
            else:
                if not detected_items:
                    st.warning("Keine relevanten Lebensmittel erkannt.")
                else:
                    st.subheader("Erkannte Lebensmittel")
                    for item in detected_items:
                        if item["score"] < CONFIDENCE_THRESHOLD:
                            continue
                        st.write(f"- **{item['name']}** ({item['score']:.2f})")

                    st.subheader("Rezeptideen (aus Backend)")

                    # Filter: nur Rezepte, bei denen alles vorhanden ist
                    only_full = st.checkbox(
                        "Nur Rezepte anzeigen, für die alle Zutaten vorhanden sind",
                        value=False,
                    )

                    try:
                        suggestions = call_backend_recipes(detected_items)
                    except requests.HTTPError as e:
                        st.error(f"HTTP-Fehler vom Backend (/suggest-recipes/): {e.response.text}")
                    except Exception as e:
                        st.error(f"Fehler bei der Rezeptberechnung: {e}")
                    else:
                        if not suggestions:
                            st.info(
                                "Für diese Kombination sind im Backend noch keine Rezepte hinterlegt."
                            )
                        else:
                            for s in suggestions:
                                name = s.get("name", "Unbenanntes Rezept")
                                ingredients = s.get("ingredients", [])
                                steps = s.get("steps", [])
                                have = s.get("have", [])
                                missing = s.get("missing", [])
                                total = s.get("total", len(ingredients))

                                if only_full and missing:
                                    continue

                                match_info = f"{len(have)}/{total} Zutaten vorhanden"

                                st.markdown(f"### 🍽️ {name} ({match_info})")
                                st.write("**Zutaten:** ", ", ".join(ingredients))
                                st.write(
                                    "✅ Bereits erkannt:",
                                    ", ".join(have) if have else "–",
                                )
                                st.write(
                                    "🛒 Noch einkaufen:",
                                    ", ".join(missing) if missing else "Nichts, alles da!",
                                )

                                with st.expander("Zubereitung anzeigen"):
                                    for i, step in enumerate(steps, start=1):
                                        st.write(f"{i}. {step}")
