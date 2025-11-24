import os
import base64
from typing import List, Dict, Any

import requests
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# === Clarifai-Konfiguration ===

USER_ID = "epicureanapps"
APP_ID = "fridge-ai-app"
MODEL_ID = "food-item-recognition"
MODEL_VERSION_ID = "1d5fd481e0cf4826aa72ec3ff049e044"

API_URL = (
    f"https://api.clarifai.com/v2/users/{USER_ID}/apps/{APP_ID}/"
    f"models/{MODEL_ID}/versions/{MODEL_VERSION_ID}/outputs"
)

CONFIDENCE_THRESHOLD = 0.05  # Mindest-Sicherheit für ein erfasstes Lebensmittel
# === Einfache Demo-Rezepte (gleiche Logik wie in Streamlit) ===

RECIPE_DB = [
    {
        "name": "Tomato Mozzarella Sandwich",
        "ingredients": ["bread", "cheese", "tomato", "lettuce"],
        "steps": [
            "Brot in Scheiben schneiden und ggf. toasten.",
            "Tomaten und Salat waschen und in Scheiben schneiden.",
            "Käse auf das Brot legen, mit Tomate und Salat belegen.",
            "Mit Salz, Pfeffer und etwas Öl oder Butter abschmecken.",
        ],
    },
    {
        "name": "Simple Cheese Omelette",
        "ingredients": ["egg", "cheese", "butter"],
        "steps": [
            "Eier in einer Schüssel verquirlen.",
            "Butter in einer Pfanne erhitzen.",
            "Eier in die Pfanne geben und stocken lassen.",
            "Käse dazugeben, zusammenklappen und kurz weiterbraten.",
        ],
    },
    {
        "name": "Garlic Bread",
        "ingredients": ["bread", "butter", "garlic"],
        "steps": [
            "Backofen vorheizen.",
            "Butter mit Knoblauch verrühren.",
            "Brot mit der Mischung bestreichen.",
            "Im Ofen goldbraun backen.",
        ],
    },
    {
        "name": "Shrimp Pasta",
        "ingredients": ["shrimp", "garlic", "butter", "pasta", "cheese"],
        "steps": [
            "Pasta in Salzwasser al dente kochen.",
            "Butter und Knoblauch in einer Pfanne erhitzen.",
            "Shrimps kurz scharf anbraten.",
            "Pasta dazugeben, mit Käse bestreuen und servieren.",
        ],
    },
]


# === Pydantic-Modelle für /suggest-recipes/ ===

class DetectedItem(BaseModel):
    name: str
    score: float


class RecipeSuggestionRequest(BaseModel):
    items: List[DetectedItem]


# === FastAPI-App ===

app = FastAPI(
    title="Fridge AI Backend",
    description="Image → Food-Items-Erkennung über Clarifai (REST)",
    version="0.1.0",
)

# CORS offen lassen für Prototypen (später enger machen)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # später: Domains deiner App
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def call_clarifai(image_bytes: bytes) -> List[Dict[str, Any]]:
    """
    Schickt Bildbytes per REST an Clarifai und gibt eine
    sortierte Liste erkannter Lebensmittel zurück.
    """
    clarifai_pat = os.environ.get("CLARIFAI_PAT")
    if not clarifai_pat:
        raise RuntimeError(
            "CLARIFAI_PAT ist nicht gesetzt. Bitte im Terminal z.B. ausführen:\n"
            'export CLARIFAI_PAT="DEIN_FUNKTIONSFÄHIGER_PAT"'
        )

    # Bild base64-kodieren
    image_b64 = base64.b64encode(image_bytes).decode("utf-8")

    headers = {
        "Authorization": f"Key {clarifai_pat}",
        "Content-Type": "application/json",
    }

    payload = {
        "inputs": [
            {
                "data": {
                    "image": {"base64": image_b64}
                }
            }
        ]
    }

    resp = requests.post(API_URL, headers=headers, json=payload)
    try:
        resp.raise_for_status()
    except requests.HTTPError as e:
        raise RuntimeError(f"HTTP-Fehler von Clarifai: {e}, Body: {resp.text}") from e

    data = resp.json()

    status = data.get("status", {})
    if status.get("code") != 10000:
        # 10000 = SUCCESS bei Clarifai
        raise RuntimeError(f"Clarifai-Statusfehler: {status}")

    outputs = data.get("outputs", [])
    if not outputs:
        return []

    concepts = outputs[0]["data"].get("concepts", [])

    items = [
        {
            "name": c["name"].lower(),
            "score": float(c["value"]),
        }
        for c in concepts
        if float(c["value"]) >= CONFIDENCE_THRESHOLD
    ]

    items = sorted(items, key=lambda x: x["score"], reverse=True)
    return items

def compute_recipe_suggestions(detected_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Nimmt erkannte Lebensmittel und liefert passende Rezepte mit
    bereits vorhandenen und fehlenden Zutaten.
    """
    detected_names = {item["name"] for item in detected_items}
    suggestions: List[Dict[str, Any]] = []

    for recipe in RECIPE_DB:
        ingredients = set(recipe["ingredients"])
        have = ingredients & detected_names
        missing = ingredients - detected_names

        if have:
            suggestions.append(
                {
                    "name": recipe["name"],
                    "ingredients": recipe["ingredients"],
                    "steps": recipe["steps"],
                    "have": sorted(list(have)),
                    "missing": sorted(list(missing)),
                    "total": len(ingredients),
                }
            )

    suggestions = sorted(
        suggestions,
        key=lambda r: len(r["have"]),
        reverse=True,
    )

    return suggestions

@app.post("/analyze-image/", summary="Bild analysieren und Lebensmittel erkennen")
async def analyze_image(file: UploadFile = File(...)):
    """
    Nimmt ein hochgeladenes Bild entgegen, ruft Clarifai auf
    und gibt erkannte Lebensmittel zurück.
    """
    # Dateityp grob prüfen
    if file.content_type not in ("image/jpeg", "image/png", "image/webp", "image/jpg"):
        raise HTTPException(status_code=400, detail="Bitte ein Bild (JPEG/PNG/WEBP) hochladen.")

    try:
        image_bytes = await file.read()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Bild konnte nicht gelesen werden: {e}")

    try:
        items = call_clarifai(image_bytes)
    except RuntimeError as e:
        # interne Fehler, z.B. CLARIFAI_PAT fehlt oder Clarifai-Statusfehler
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unerwarteter Fehler: {e}")

    return JSONResponse(content={"items": items})

@app.post("/suggest-recipes/", summary="Aus erkannten Lebensmitteln Rezeptvorschläge generieren")
async def suggest_recipes_endpoint(payload: RecipeSuggestionRequest):
    """
    Erwartet eine Liste erkannter Lebensmittel (name + score)
    und liefert passende Rezepte zurück.
    """

    # Items in ein einfaches Dict-Format bringen
    detected_items = [
        {"name": item.name.lower(), "score": float(item.score)}
        for item in payload.items
    ]

    suggestions = compute_recipe_suggestions(detected_items)

    return JSONResponse(content={"suggestions": suggestions})

@app.get("/health", summary="Health-Check für das Backend")
async def health():
    """
    Einfacher Health-Check-Endpunkt.
    Gibt 'ok' zurück, wenn der Server läuft.
    """
    return {"status": "ok"}
