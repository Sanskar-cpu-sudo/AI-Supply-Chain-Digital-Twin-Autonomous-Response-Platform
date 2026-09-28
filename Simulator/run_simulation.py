"""
CLI entrypoint for the simulator.

Usage:
    # Seed a company with realistic baseline data (suppliers, products,
    # warehouses, inventory, order/shipment history):
    python run_simulation.py seed --company "Acme Corp"

    # Trigger a specific event against a company's existing data:
    python run_simulation.py trigger --company "Acme Corp" --event SHIPMENT_DELAY
    python run_simulation.py trigger --company "Acme Corp" --event SUPPLIER_DELAY --delay-days 5
    python run_simulation.py trigger --company "Acme Corp" --event DEMAND_SPIKE

    # List available event types:
    python run_simulation.py list-events
"""
import argparse
import json
import sys

from db import get_session
from events import EVENT_REGISTRY
from generator import generate_baseline

sys.path.insert(0, ".")
from app.models.company import Company  # noqa: E402


def cmd_seed(args):
    with get_session() as db:
        company = db.query(Company).filter(Company.name == args.company).first()
        if company is None:
            print(f"Company '{args.company}' not found. Register a user under that "
                  f"company name via POST /auth/register first, then re-run seed.")
            return
        summary = generate_baseline(db, company.id, num_historical_orders=args.orders)
        print(f"Baseline seeded for '{args.company}':")
        print(json.dumps(summary, indent=2))


def cmd_trigger(args):
    if args.event not in EVENT_REGISTRY:
        print(f"Unknown event '{args.event}'. Use 'list-events' to see options.")
        return
    with get_session() as db:
        company = db.query(Company).filter(Company.name == args.company).first()
        if company is None:
            print(f"Company '{args.company}' not found.")
            return
        fn = EVENT_REGISTRY[args.event]
        kwargs = {}
        if args.delay_days is not None:
            kwargs["delay_days"] = args.delay_days
        result = fn(db, company.id, **kwargs)
        print(json.dumps(result, indent=2))


def cmd_list_events(args):
    for name in EVENT_REGISTRY:
        print(name)


def main():
    parser = argparse.ArgumentParser(description="AI Supply Chain simulator")
    sub = parser.add_subparsers(dest="command", required=True)

    seed_p = sub.add_parser("seed", help="Seed baseline data for a company")
    seed_p.add_argument("--company", required=True)
    seed_p.add_argument("--orders", type=int, default=20, help="Number of historical orders to generate")
    seed_p.set_defaults(func=cmd_seed)

    trigger_p = sub.add_parser("trigger", help="Inject a specific event")
    trigger_p.add_argument("--company", required=True)
    trigger_p.add_argument("--event", required=True, choices=list(EVENT_REGISTRY.keys()))
    trigger_p.add_argument("--delay-days", type=int, default=None)
    trigger_p.set_defaults(func=cmd_trigger)

    list_p = sub.add_parser("list-events", help="List available event types")
    list_p.set_defaults(func=cmd_list_events)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()