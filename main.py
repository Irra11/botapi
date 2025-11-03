from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, Form, status, Response
from fastapi.responses import FileResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import shutil
import os
import uuid
import time
from typing import List, Optional, Dict, Any
import re

# --- Configuration and Setup ---

# Directory to save uploaded images
UPLOAD_DIR = "images"
if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)

app = FastAPI(title="NhoyHub Order API")

# Allow connections from your local machine (browser and Uvicorn)
origins = [
    "http://127.0.0.1:5500", 
    "http://localhost:5500",
    "http://127.0.0.1:8000",
    "http://localhost:8000",
    "http://127.0.0.1",
    "http://localhost"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- In-Memory Database (Data resets on server restart) ---
orders_db = []
config_db = {
    "public_image_url": "https://via.placeholder.com/600x400/9C27B0/ffffff?text=Public+Image",
    "esign_image_1": "",
    "esign_image_2": "",
    "esign_image_3": "",
    "esign_image_4": "",
    "esign_image_5": "",
}

# --- Admin Credentials ---
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "password123"
ADMIN_TOKEN = "fake-jwt-token-for-admin" 

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

# --- Models ---
class OrderBase(BaseModel):
    name: str = Field(..., max_length=100)
    udid: str = Field(..., max_length=50)

class OrderOut(OrderBase):
    id: int
    image_url: str
    status: str
    download_link: Optional[str] = None
    created_at: float
    price: Optional[str] = None

class OrderListResponse(BaseModel):
    items: List[OrderOut]
    total: int
    page: int
    page_size: int

class Token(BaseModel):
    access_token: str
    token_type: str = "Bearer"

class ConfigUpdate(BaseModel):
    public_image_url: Optional[str] = None
    url: Optional[str] = None 

# --- Security Dependency ---

def get_current_user(token: str = Depends(oauth2_scheme)):
    """Validates the admin token."""
    if token != ADMIN_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return ADMIN_USERNAME

# --- Helper Functions ---

def save_upload_file(upload_file: UploadFile, order_id: int) -> str:
    """Saves the uploaded image and returns the relative URL."""
    if not os.path.exists(UPLOAD_DIR):
        os.makedirs(UPLOAD_DIR)

    filename = f"order_{order_id}_{uuid.uuid4().hex[:8]}_{upload_file.filename}"
    file_path = os.path.join(UPLOAD_DIR, filename)
    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(upload_file.file, buffer)
    except Exception:
        raise HTTPException(status_code=500, detail="Could not save uploaded file")
    finally:
        # Crucial: Close the file stream after copying
        upload_file.file.close() 
    return f"/{UPLOAD_DIR}/{filename}"

def extract_price_from_name(name: str) -> str:
    """Extracts price (e.g., "$999") from the name string."""
    match = re.search(r'\$(\d+)', name)
    return match.group(1) if match else "N/A"

# --- Startup ---

@app.on_event("startup")
async def startup_event():
    # Pre-populate some dummy data
    for i in range(1, 26):
        orders_db.append({
            "id": i,
            "name": f"Dummy Item {i} ${100 + i}",
            "udid": f"dummy-{i}-{uuid.uuid4().hex[:12]}",
            "image_url": "/images/default.jpg", 
            "status": "approved" if i % 3 == 0 else ("rejected" if i % 5 == 0 else "pending"),
            "download_link": f"http://example.com/download/{i}" if i % 3 == 0 else None,
            "created_at": time.time() - (i * 3600),
        })
    # Create a default image placeholder file
    if not os.path.exists(os.path.join(UPLOAD_DIR, "default.jpg")):
        try:
            with open(os.path.join(UPLOAD_DIR, "default.jpg"), "w") as f:
                f.write("A placeholder image should be here.")
        except IOError:
            print("Warning: Could not create default.jpg placeholder file.")

# --- Endpoints ---

@app.post("/login", response_model=Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    if form_data.username != ADMIN_USERNAME or form_data.password != ADMIN_PASSWORD:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return {"access_token": ADMIN_TOKEN, "token_type": "bearer"}

@app.get("/images/{filename}")
async def get_image(filename: str):
    """Serves static image files."""
    file_path = os.path.join(UPLOAD_DIR, filename)
    if not os.path.exists(file_path):
        default_path = os.path.join(UPLOAD_DIR, "default.jpg")
        if os.path.exists(default_path):
            file_path = default_path
        else:
            raise HTTPException(status_code=404, detail="Image not found")
    
    return FileResponse(file_path, media_type="application/octet-stream") 

@app.post("/orders", status_code=status.HTTP_201_CREATED, response_model=OrderOut)
async def create_order(name: str = Form(...), udid: str = Form(...), image: UploadFile = File(...)):
    new_id = len(orders_db) + 1
    image_url = save_upload_file(image, new_id)
    
    new_order = {
        "id": new_id,
        "name": name,
        "udid": udid,
        "image_url": image_url,
        "status": "pending",
        "download_link": None,
        "created_at": time.time(),
        "price": extract_price_from_name(name)
    }
    orders_db.append(new_order)
    return new_order

@app.get("/orders", response_model=OrderListResponse)
async def list_orders(
    page: int = 1, 
    page_size: int = 12, 
    status: Optional[str] = None, 
    q: Optional[str] = None
):
    filtered_orders = orders_db
    
    if status and status.lower() in ["pending", "approved", "rejected"]:
        filtered_orders = [o for o in filtered_orders if o["status"].lower() == status.lower()]
        
    if q:
        q_lower = q.lower()
        filtered_orders = [
            o for o in filtered_orders 
            if q_lower in o["name"].lower() or q_lower in o["udid"].lower()
        ]

    sorted_orders = sorted(filtered_orders, key=lambda x: x['created_at'], reverse=True)

    start = (page - 1) * page_size
    end = start + page_size
    
    items = [
        {**o, "price": extract_price_from_name(o["name"])} 
        for o in sorted_orders[start:end]
    ]

    return {
        "items": items,
        "total": len(filtered_orders),
        "page": page,
        "page_size": page_size
    }

@app.get("/orders/{order_id}", response_model=OrderOut)
async def get_order(order_id: int, admin: str = Depends(get_current_user)):
    order = next((o for o in orders_db if o["id"] == order_id), None)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return {**order, "price": extract_price_from_name(order["name"])}

@app.put("/orders/{order_id}", response_model=OrderOut)
async def update_order(
    order_id: int,
    name: str = Form(...), 
    udid: str = Form(...), 
    status: str = Form(...),
    download_link: Optional[str] = Form(None),
    image: Optional[UploadFile] = File(None),
    admin: str = Depends(get_current_user)
):
    order_index = next((i for i, o in enumerate(orders_db) if o["id"] == order_id), -1)
    if order_index == -1:
        raise HTTPException(status_code=404, detail="Order not found")

    order = orders_db[order_index]
    
    if image and image.filename:
        order["image_url"] = save_upload_file(image, order_id)
        
    order["name"] = name
    order["udid"] = udid
    order["status"] = status
    order["download_link"] = download_link if download_link else None
    order["price"] = extract_price_from_name(name)

    return order

@app.delete("/orders/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_order(order_id: int, admin: str = Depends(get_current_user)):
    global orders_db
    initial_length = len(orders_db)
    orders_db = [o for o in orders_db if o["id"] != order_id]
    
    if len(orders_db) == initial_length:
        raise HTTPException(status_code=404, detail="Order not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)

@app.get("/config", response_model=Dict[str, Optional[str]])
async def get_config(admin: str = Depends(get_current_user)):
    return config_db

@app.put("/config/public")
async def update_public_image_url(update: ConfigUpdate, admin: str = Depends(get_current_user)):
    if update.public_image_url is None:
        raise HTTPException(status_code=400, detail="Missing public_image_url field")
        
    config_db["public_image_url"] = update.public_image_url
    return {"message": "Public image URL updated", "public_image_url": update.public_image_url}

@app.put("/config/esign/{index}")
async def update_esign_image_url(index: int, update: ConfigUpdate, admin: str = Depends(get_current_user)):
    if not 1 <= index <= 5:
        raise HTTPException(status_code=400, detail="Esign index must be between 1 and 5")
    
    if update.url is None:
        raise HTTPException(status_code=400, detail="Missing url field")

    key = f"esign_image_{index}"
    config_db[key] = update.url
    return {"message": f"Esign image {index} updated", key: update.url}
