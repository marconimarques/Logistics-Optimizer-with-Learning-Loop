from pydantic import BaseModel
from typing import Any, Dict, List, Optional


class SolverParams(BaseModel):
    objective: Optional[str] = "Total Cost"
    max_delivery_time: Optional[float] = None
    max_vehicles_per_warehouse: Optional[int] = None
    min_service_coverage: Optional[float] = None


class SolverOutput(BaseModel):
    warehouse_opening: Dict[str, Any]
    zone_assignments: Dict[str, Any]
    vehicle_allocation: Dict[str, Any]
    total_cost: float
    avg_delivery_time: float
    service_coverage: float
    is_feasible: bool = True


class SolverResult(BaseModel):
    scenario_name: str
    params: SolverParams
    output: SolverOutput


class InteractionRecord(BaseModel):
    schema_version: int = 1
    event_id: str
    session_id: str
    session_timestamp: str
    turn_index: int
    query_text: str
    inferred_params: Dict[str, Any]
    solver_calls: List[Dict[str, Any]]
    solver_call_count: int
    agent_turn_count: int


class SessionRatingRecord(BaseModel):
    event_type: str = "session_rating"
    session_id: str
    rating: int
    total_queries: int
    total_solver_calls: int
    timestamp: str
