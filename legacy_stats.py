from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

router = APIRouter()

# Decoupled rules dictionary to allow easy modification and extension
MISSION_RULES = {
    1: ("recon", 10.0),
    2: ("transport", 5.0),
}
MAX_SCORE = 100.0


class MissionStatsRequest(BaseModel):
    """Pydantic model validating incoming payloads."""
    type: int = Field(
        ..., description="Mission type ID (e.g., 1 or 2)"
    )
    dist: float = Field(..., description="Total distance covered")
    batt: float = Field(..., description="Battery consumption percentage")
    payload_weight: float = Field(
        default=0.0, description="Payload weight in kilograms"
    )


def _compute_base_score(
    distance: float, battery: float, multiplier: float
) -> float:
    """Computes basic mission performance score safely."""
    if distance <= 0.0 or battery <= 0.0:
        return 0.0
    return (distance * multiplier) / battery


def _cap_score(score: float) -> float:
    """Caps the mission score to prevent values exceeding limits."""
    return min(score, MAX_SCORE)


@router.post("/api/mission_stats")
def calc_stats(data: MissionStatsRequest):
    # 1. Resolve mission validation with a guard clause
    mission = MISSION_RULES.get(data.type)
    if not mission:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid mission type"
        )

    status_name, multiplier = mission
    score = _compute_base_score(data.dist, data.batt, multiplier)

    # 2. Process conditional transport penalties
    is_transport = status_name == "transport"
    heavy_payload = data.payload_weight > 50.0
    if is_transport and heavy_payload and score > 0.0:
        score -= (data.payload_weight * 0.1)

    # 3. Apply capping using our helper function
    final_score = _cap_score(score)

    # 4. Safe parameterized representation of query logging
    # (prevents SQL injection practices)
    query = "INSERT INTO stats (mission, score) VALUES (?, ?)"
    print(
        f"[DB LOG PARAMETERIZED] {query} with variables: "
        f"({status_name}, {final_score})"
    )

    return {
        "status": "success",
        "mission": status_name,
        "final_score": round(final_score, 2)
    }