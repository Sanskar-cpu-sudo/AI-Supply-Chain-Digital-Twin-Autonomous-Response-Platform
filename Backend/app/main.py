from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes import actions, auth, documents, health, incidents, inventory, monitoring, orders, products, recommendations, shipments, suppliers, warehouses, websocket

app = FastAPI(title="AI Supply Chain Digital Twin & Autonomous Response Platform", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(suppliers.router)
app.include_router(products.router)
app.include_router(warehouses.router)
app.include_router(inventory.router)
app.include_router(orders.router)
app.include_router(shipments.router)
app.include_router(monitoring.router)
app.include_router(incidents.router)
app.include_router(documents.router)
app.include_router(recommendations.router)
app.include_router(actions.router)
app.include_router(websocket.router)


@app.get("/")
def root():
    return {"message": "AI Supply Chain API is running. See /docs for the interactive API explorer."}