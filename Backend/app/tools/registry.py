"""
Wraps the raw tool functions (shipment_tools.py etc) as LangChain tool
objects the Investigation Agent (Phase 12) can bind to an LLM.

Why a factory function instead of module-level @tool decorators:
each agent run happens inside one HTTP request, with one DB session
and one company_id already known from the authenticated user. LangChain
tools called by name from an LLM response can't take extra positional
args at call time -- so we close over (db, company_id) here and hand
the agent a fresh, correctly-scoped set of tools for that one request.
This also means one company's agent run can never accidentally see
another company's data through a tool call.

Tool docstrings matter a lot here -- they're literally what the LLM
reads to decide which tool to call and with what arguments. Phase 13's
"tool selection accuracy" eval metric is really measuring how well
these descriptions work.
"""
from langchain_core.tools import tool

from app.tools.document_tools import search_company_documents as _search_company_documents
from app.tools.inventory_tools import get_inventory as _get_inventory
from app.tools.order_tools import get_orders as _get_orders
from app.tools.shipment_tools import get_shipment as _get_shipment
from app.tools.supplier_tools import get_supplier as _get_supplier
from app.tools.warehouse_tools import get_warehouse as _get_warehouse


def build_investigation_tools(db, company_id) -> list:
    """Returns the full tool list for the Investigation Agent (Phase 12)."""

    @tool
    def get_shipment(shipment_id: str) -> dict:
        """Get full details of a shipment by its id: status, quantity, expected/actual
        delivery dates, delay_days, and which supplier/product/warehouse it's tied to.
        Use this first when investigating a shipment_delay incident."""
        return _get_shipment(db, company_id, shipment_id)

    @tool
    def get_supplier(supplier_id: str) -> dict:
        """Get details of a supplier by id: name, contact info, reliability_score (0-1),
        and whether they're approved. Use this to check if a supplier's reliability
        history explains a delay, or to evaluate them as a backup option."""
        return _get_supplier(db, company_id, supplier_id)

    @tool
    def get_inventory(product_id: str = "", warehouse_id: str = "") -> dict:
        """Get current stock levels. Provide product_id and/or warehouse_id to filter;
        omit both to get an error (too broad). Returns quantity_on_hand, reorder_point,
        safety_stock, and whether each row is already below its reorder point.
        Use this to assess stockout risk from a delay or demand spike."""
        return _get_inventory(db, company_id, product_id or None, warehouse_id or None)

    @tool
    def get_orders(product_id: str = "", limit: int = 20) -> dict:
        """Get recent customer orders, optionally filtered by product_id. Returns each
        order's quantity and status, plus total_quantity_at_risk (sum of pending/at_risk
        order quantities). Use this to quantify how many orders/units are affected."""
        return _get_orders(db, company_id, product_id or None, limit)

    @tool
    def get_warehouse(warehouse_id: str) -> dict:
        """Get details of a warehouse by id: name, location, capacity.
        Use this for context when a warehouse is implicated in an incident."""
        return _get_warehouse(db, company_id, warehouse_id)

    @tool
    def search_company_documents(query: str) -> dict:
        """Search company policy and supplier contract documents for relevant context
        (e.g. approved backup suppliers, minimum order quantities, SLA terms).
        Returns the top 3 most relevant chunks with their source document title."""
        return _search_company_documents(db, company_id, query)

    return [get_shipment, get_supplier, get_inventory, get_orders, get_warehouse, search_company_documents]