import os
import base64
import json
from typing import List, Dict, Any

import requests
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from openai import OpenAI

# === Clarifai configuration ===

USER_ID = "epicureanapps"
APP_ID = "fridge-ai-app"
MODEL_ID = "food-item-recognition"
MODEL_VERSION_ID = "1d5fd481e0cf4826aa72ec3ff049e044"

API_URL = (
    f"https://api.clarifai.com/v2/users/{USER_ID}/apps/{APP_ID}/"
    f"models/{MODEL_ID}/versions/{MODEL_VERSION_ID}/outputs"
)

CONFIDENCE_THRESHOLD = 0.05  # minimum confidence for a detected food item

# === Simple demo recipe DB (optional / legacy) ===

RECIPE_DB = [
    {
        "name": "Tomato Mozzarella Sandwich",
        "ingredients": ["bread", "cheese", "tomato", "lettuce"],
        "steps": [
            "Slice the bread and toast if desired.",
            "Wash and slice tomatoes and lettuce.",
            "Layer cheese, tomato, and lettuce on the bread.",
            "Season with salt, pepper and a bit of oil or butter.",
        ],
    },
    {
        "name": "Simple Cheese Omelette",
        "ingredients": ["egg", "cheese", "butter"],
        "steps": [
            "Beat the eggs in a bowl.",
            "Melt butter in a pan.",
            "Pour in the eggs and let them set.",
            "Add cheese, fold and cook briefly.",
        ],
    },
    {
        "name": "Garlic Bread",
        "ingredients": ["bread", "butter", "garlic"],
        "steps": [
            "Preheat the oven.",
            "Mix butter with minced garlic.",
            "Spread the mixture on the bread.",
            "Bake until golden brown.",
        ],
    },
    {
        "name": "Shrimp Pasta",
        "ingredients": ["shrimp", "garlic", "butter", "pasta", "cheese"],
        "steps": [
            "Cook pasta in salted water until al dente.",
            "Heat butter and garlic in a pan.",
            "Sear the shrimp briefly.",
            "Add pasta, toss, sprinkle with cheese and serve.",
        ],
    },
]

# === Pydantic models ===

from typing import List, Dict, Any, Optional
from pydantic import BaseModel

class DetectedItem(BaseModel):
    name: str
    score: float


class RecipeAIRequest(BaseModel):
    """
    Used by /ai-recipes/ – the frontend sends a list of detected items.
    """
    items: List[DetectedItem]


class RecipeFeedbackRequest(BaseModel):
    """
    Used by /feedback/ – when user clicks 👍 or 👎 on a specific recipe.
    """
    recipe_name: str
    liked: bool
    ingredients: List[str] = []
    have: List[str] = []
    missing: List[str] = []
    source: Optional[str] = None


# === FastAPI app ===

app = FastAPI(
    title="Fridge AI Backend",
    description="Image → food item detection via Clarifai (REST) + AI recipes via OpenAI",
    version="0.2.0",
)

# OpenAI client (API key must be set as environment variable OPENAI_API_KEY)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

# CORS – open for prototyping (can be restricted later)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # later: restrict to your domains
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# === Clarifai call ===

def call_clarifai(image_bytes: bytes) -> List[Dict[str, Any]]:
    """
    Sends image bytes to Clarifai via REST and returns
    a sorted list of detected food items.
    """
    clarifai_pat = os.environ.get("CLARIFAI_PAT")
    if not clarifai_pat:
        raise RuntimeError(
            "CLARIFAI_PAT is not set. Please set it, e.g.:\n"
            'export CLARIFAI_PAT="YOUR_WORKING_PAT"'
        )

    # base64 encode the image
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
        raise RuntimeError(f"HTTP error from Clarifai: {e}, Body: {resp.text}") from e

    data = resp.json()

    status = data.get("status", {})
    if status.get("code") != 10000:  # 10000 = SUCCESS
        raise RuntimeError(f"Clarifai status error: {status}")

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


# Optional: still here, even if we mainly switch to AI recipes
def compute_recipe_suggestions(detected_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
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


# === Routes ===

@app.post("/analyze-image/", summary="Analyse image and detect food items")
async def analyze_image(file: UploadFile = File(...)):
    """
    Takes an uploaded image, calls Clarifai and returns detected food items.
    """
    if file.content_type not in ("image/jpeg", "image/png", "image/webp", "image/jpg"):
        raise HTTPException(status_code=400, detail="Please upload an image (JPEG/PNG/WEBP).")

    try:
        image_bytes = await file.read()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not read image: {e}")

    try:
        items = call_clarifai(image_bytes)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {e}")

    return JSONResponse(content={"items": items})


@app.post("/ai-recipes/")
async def ai_recipes(payload: RecipeAIRequest) -> Dict[str, Any]:
    """
    Takes detected items and asks OpenAI for recipe ideas.
    Returns: {"suggestions": [ ...recipes... ]}
    """
    if not OPENAI_API_KEY:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY not configured")

    ingredient_list = [item.name.lower() for item in payload.items if item.name]

    if not ingredient_list:
        raise HTTPException(status_code=400, detail="No ingredients provided")

    system_prompt = (
        "You are a helpful cooking assistant. "
        "The user has some ingredients available. "
        "Suggest 3 realistic, home-cook friendly recipes. "
        "Each recipe should have: name, ingredients list, step-by-step instructions, "
        "and two lists: 'have' (ingredients already available) and 'missing' (what to buy). "
        "Keep recipes simple, 20–40 minutes cooking time. "
        "Respond ONLY with valid JSON."
    )

    user_prompt = (
        "Available ingredients: " + ", ".join(ingredient_list) + ".\n"
        "Return a JSON object with exactly this structure:\n"
        "{\n"
        '  \"recipes\": [\n'
        "    {\n"
        '      \"name\": \"...\",\n'
        '      \"ingredients\": [\"...\", \"...\"],\n'
        '      \"steps\": [\"step 1\", \"step 2\", \"...\"],\n'
        '      \"have\": [\"...\"],\n'
        '      \"missing\": [\"...\"]\n'
        "    }\n"
        "  ]\n"
        "}"
    )

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.5,
        )
        content = response.choices[0].message.content
        data = json.loads(content)
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=500,
            detail="Could not parse AI response as JSON",
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"AI error: {e}",
        )

    recipes = data.get("recipes", [])

    return {"suggestions": recipes}


@app.post("/feedback/")
async def feedback(payload: RecipeFeedbackRequest) -> Dict[str, Any]:
    """
    Receives user feedback for a specific recipe (like/dislike).
    For now we just log it or return 'ok'.
    Later you can store this in a DB or logfile.
    """
    # For debugging, you can log this on the server:
    print("FEEDBACK RECEIVED:", payload.dict())

    return {"status": "ok"}


@app.get("/health", summary="Simple health-check")
async def health():
    return {"status": "ok"}
