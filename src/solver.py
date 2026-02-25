import pyomo.environ as pyo
from src.models import SolverParams, SolverOutput, SolverResult


class SolverError(Exception):
    """Raised when Pyomo/HiGHS encounters an internal failure."""


def run_solver(params: SolverParams) -> SolverResult:
    """
    Build and solve the MILP using Pyomo + HiGHS.
    Returns SolverResult with output metrics and assignments.
    Raises SolverError if Pyomo/HiGHS encounters an internal failure.
    """
    try:
        model = pyo.ConcreteModel()

        # Data
        warehouses = ['Urban-1', 'Urban-2', 'Suburban-1', 'Suburban-2', 'Industrial-1']
        zones = [f'Zone-{i}' for i in range(1, 21)]

        warehouse_data = {
            'Urban-1':      {'fixed': 800000, 'capacity': 15000, 'base_time': 0.8},
            'Urban-2':      {'fixed': 850000, 'capacity': 12000, 'base_time': 0.9},
            'Suburban-1':   {'fixed': 600000, 'capacity': 18000, 'base_time': 1.2},
            'Suburban-2':   {'fixed': 650000, 'capacity': 16000, 'base_time': 1.1},
            'Industrial-1': {'fixed': 500000, 'capacity': 25000, 'base_time': 1.8},
        }

        zone_demand = {f'Zone-{i}': 800 + i * 50 for i in range(1, 21)}
        delivery_times = {
            (w, z): warehouse_data[w]['base_time'] + 0.1 * (hash(z) % 10)
            for w in warehouses for z in zones
        }

        # Variables
        model.y = pyo.Var(warehouses, domain=pyo.Binary)
        model.x = pyo.Var(warehouses, zones, domain=pyo.Binary)
        model.v = pyo.Var(warehouses, domain=pyo.NonNegativeIntegers, bounds=(0, 10))

        # Objective
        if params.objective == 'Total Cost':
            model.obj = pyo.Objective(
                expr=(
                    sum(warehouse_data[w]['fixed'] * model.y[w] for w in warehouses) +
                    sum(50000 * model.v[w] for w in warehouses) +
                    sum(
                        delivery_times[w, z] * zone_demand[z] * 2 * model.x[w, z]
                        for w in warehouses for z in zones
                    )
                ),
                sense=pyo.minimize,
            )
        elif params.objective == 'Delivery Time':
            model.obj = pyo.Objective(
                expr=sum(delivery_times[w, z] * model.x[w, z] for w in warehouses for z in zones),
                sense=pyo.minimize,
            )
        elif params.objective == 'Fleet Utilization':
            model.obj = pyo.Objective(
                expr=sum(model.v[w] for w in warehouses),
                sense=pyo.minimize,
            )
        else:  # Service Coverage
            model.obj = pyo.Objective(
                expr=sum(model.x[w, z] for w in warehouses for z in zones),
                sense=pyo.maximize,
            )

        # Constraints
        for z in zones:
            model.add_component(
                f'assign_{z}',
                pyo.Constraint(expr=sum(model.x[w, z] for w in warehouses) <= 1),
            )

        for w in warehouses:
            model.add_component(
                f'capacity_{w}',
                pyo.Constraint(
                    expr=sum(zone_demand[z] * model.x[w, z] for z in zones)
                         <= warehouse_data[w]['capacity'] * model.y[w]
                ),
            )

        for w in warehouses:
            model.add_component(
                f'vehicles_{w}',
                pyo.Constraint(
                    expr=model.v[w] >= sum(zone_demand[z] * model.x[w, z] for z in zones) / 3000
                ),
            )

        if params.max_delivery_time:
            for w in warehouses:
                for z in zones:
                    if delivery_times[w, z] > params.max_delivery_time:
                        model.add_component(
                            f'time_limit_{w}_{z}',
                            pyo.Constraint(expr=model.x[w, z] == 0),
                        )

        if params.max_vehicles_per_warehouse:
            for w in warehouses:
                model.add_component(
                    f'fleet_limit_{w}',
                    pyo.Constraint(expr=model.v[w] <= params.max_vehicles_per_warehouse),
                )

        if params.min_service_coverage:
            model.coverage_constraint = pyo.Constraint(
                expr=sum(model.x[w, z] for w in warehouses for z in zones)
                     >= params.min_service_coverage * len(zones)
            )

        # Solve
        solver = pyo.SolverFactory('appsi_highs')
        result = solver.solve(model)

        is_feasible = (
            result.solver.termination_condition == pyo.TerminationCondition.optimal
        )

        if is_feasible:
            warehouse_opening = {w: int(pyo.value(model.y[w])) for w in warehouses}
            zone_assignments = {
                z: next((w for w in warehouses if pyo.value(model.x[w, z]) > 0.5), None)
                for z in zones
            }
            vehicle_allocation = {
                w: int(pyo.value(model.v[w]))
                for w in warehouses if pyo.value(model.y[w]) > 0.5
            }

            total_cost = (
                sum(warehouse_data[w]['fixed'] * pyo.value(model.y[w]) for w in warehouses) +
                sum(50000 * pyo.value(model.v[w]) for w in warehouses) +
                sum(
                    delivery_times[w, z] * zone_demand[z] * 2 * pyo.value(model.x[w, z])
                    for w in warehouses for z in zones
                )
            )

            served_zones = sum(1 for z in zones if zone_assignments[z] is not None)
            service_coverage = served_zones / len(zones)

            if served_zones > 0:
                avg_delivery_time = sum(
                    delivery_times[zone_assignments[z], z]
                    for z in zones if zone_assignments[z] is not None
                ) / served_zones
            else:
                avg_delivery_time = 999.0
        else:
            warehouse_opening = {}
            zone_assignments = {}
            vehicle_allocation = {}
            total_cost = 999_999_999.0
            avg_delivery_time = 999.0
            service_coverage = 0.0

        scenario_name = params.objective or "Default Run"
        if not is_feasible:
            scenario_name += " (Infeasible)"

        return SolverResult(
            scenario_name=scenario_name,
            params=params,
            output=SolverOutput(
                warehouse_opening=warehouse_opening,
                zone_assignments=zone_assignments,
                vehicle_allocation=vehicle_allocation,
                total_cost=round(total_cost, 2),
                avg_delivery_time=round(avg_delivery_time, 2),
                service_coverage=round(service_coverage, 2),
                is_feasible=is_feasible,
            ),
        )

    except Exception as exc:
        raise SolverError(f"Solver internal failure: {exc}") from exc
