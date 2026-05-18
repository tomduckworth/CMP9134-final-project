import sqlite3
import datetime
import logging
import os
from enum import Enum
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

import requests
# Import FastAPI and HTTPException to handle app initialization and 404 errors
from fastapi import FastAPI, HTTPException
from legacy_stats import router as legacy_router  # Router from legacy stats module


# ==============================================================================
# 1. CONFIGURATION & TYPES
# ==============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-15s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)


class MissionStatus(Enum):
    """Standardized statuses for mission logging."""
    SUCCESS = "SUCCESS"
    REJECTED_BOUNDS = "REJECTED: OUT OF BOUNDS"
    UNAUTHORIZED = "REJECTED: UNAUTHORIZED"
    API_ERROR = "FAILED: API HTTP ERROR"
    CONNECTION_ERROR = "FAILED: CONNECTION LOST"


@dataclass
class Config:
    """Centralized configuration, allowing overrides via Environment Variables."""
    db_file: Path = Path(os.getenv("GCS_DB_FILE", "mission_logs.db"))
    grid_size: int = int(os.getenv("GCS_GRID_SIZE", 10))
    api_url: str = os.getenv("GCS_API_URL", "http://localhost:5000/api/move")
    api_timeout: float = float(os.getenv("GCS_API_TIMEOUT", 5.0))


# ==============================================================================
# 2. CUSTOM EXCEPTIONS
# ==============================================================================

class GroundControlError(Exception):
    """Base exception for all Ground Control Station errors."""
    pass


class SafetyBoundaryError(GroundControlError):
    """Raised when coordinates exceed safety parameters."""
    pass


class AuthenticationError(GroundControlError):
    """Raised when an unauthorized user attempts a restricted action."""
    pass


# ==============================================================================
# 3. COMPONENT CLASSES
# ==============================================================================

class User:
    """Represents a system user with authentication and role-based access."""
    def __init__(self, username: str, role: str):
        self.username = username
        self.role = role
        self.is_authenticated = False

    def login(self) -> bool:
        """Simulates authenticating a user securely."""
        self.is_authenticated = True
        logging.info(f"User '{self.username}' (Role: {self.role}) logged in.")
        return True

    def logout(self) -> None:
        """Revokes the user's active session."""
        self.is_authenticated = False
        logging.info(f"User '{self.username}' logged out.")


class AuditLogger:
    """Handles all database operations independently."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.logger = logging.getLogger("AuditLogger")
        self._initialize_schema()

    def _initialize_schema(self) -> None:
        """Sets up the database schema safely."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    commander TEXT NOT NULL,
                    target_x INTEGER NOT NULL,
                    target_y INTEGER NOT NULL,
                    status TEXT NOT NULL
                )
            ''')
        self.logger.info(f"Database ready at: {self.db_path.absolute()}")

    def record_mission(
        self, commander: str, x: int, y: int, status: MissionStatus
    ) -> None:
        """Inserts an immutable mission record."""
        timestamp = datetime.datetime.now().isoformat(sep=" ", timespec="seconds")

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO logs "
                "(timestamp, commander, target_x, target_y, status) "
                "VALUES (?, ?, ?, ?, ?)",
                (timestamp, commander, x, y, status.value)
            )


class RobotClient:
    """Handles all network communications with the physical/virtual robot."""

    def __init__(self, api_url: str, timeout: float):
        self.api_url = api_url
        self.timeout = timeout
        self.logger = logging.getLogger("RobotClient")

    def get_telemetry(self) -> dict:
        """Requests current telemetry (location, status) from the Robot API."""
        telemetry_url = self.api_url.replace("/move", "/telemetry")
        self.logger.debug(f"Requesting telemetry from: {telemetry_url}")
        try:
            response = requests.get(telemetry_url, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException:
            self.logger.warning(
                "Robot unreachable. Returning simulated offline data."
            )
            return {"x": "unknown", "y": "unknown", "status": "offline"}

    def transmit_move(self, x: int, y: int) -> None:
        """Sends payload to API. Raises exception on failure."""
        payload = {"x": x, "y": y}
        self.logger.debug(f"Transmitting payload: {payload}")

        response = requests.post(
            self.api_url, json=payload, timeout=self.timeout
        )
        response.raise_for_status()


class GroundControlStation:
    """The Main Orchestrator."""

    def __init__(self, config: Config):
        self.config = config
        self.logger = logging.getLogger("GCS_Core")
        self.db = AuditLogger(self.config.db_file)
        self.robot = RobotClient(self.config.api_url, self.config.api_timeout)

    def _validate_safety(self, x: int, y: int) -> None:
        if not (0 <= x <= self.config.grid_size and 0 <= y <= self.config.grid_size):
            raise SafetyBoundaryError(
                f"Target ({x}, {y}) exceeds authorized safety grid "
                f"(0-{self.config.grid_size})."
            )

    def _verify_authorization(self, user: User, required_role: str) -> None:
        if not user.is_authenticated:
            raise AuthenticationError(
                f"Access Denied: User '{user.username}' is not logged in."
            )
        if user.role != required_role:
            raise AuthenticationError(
                f"Access Denied: '{user.username}' lacks '{required_role}'."
            )

    def request_telemetry(self, user: User) -> Optional[dict]:
        self.logger.info(f"Telemetry requested by {user.username}")
        if not user.is_authenticated:
            self.logger.error("Telemetry access denied (Not logged in).")
            return None
        return self.robot.get_telemetry()

    def execute_move_command(self, user: User, x: int, y: int) -> bool:
        self.logger.info(
            f"Command received from {user.username}: MOVE TO ({x}, {y})"
        )

        try:
            self._verify_authorization(user, required_role="Commander")
        except AuthenticationError as e:
            self.logger.warning(f"SECURITY INTERVENTION: {e}")
            self.db.record_mission(
                user.username, x, y, MissionStatus.UNAUTHORIZED
            )
            return False

        try:
            self._validate_safety(x, y)
        except SafetyBoundaryError as e:
            self.logger.warning(f"SAFETY INTERLOCK ENGAGED: {e}")
            self.db.record_mission(
                user.username, x, y, MissionStatus.REJECTED_BOUNDS
            )
            return False

        try:
            self.robot.transmit_move(x, y)
            self.logger.info("Command executed successfully.")
            self.db.record_mission(user.username, x, y, MissionStatus.SUCCESS)
            return True
        except requests.exceptions.HTTPError as e:
            self.logger.error(f"Robot rejected command (HTTP Error): {e}")
            self.db.record_mission(
                user.username, x, y, MissionStatus.API_ERROR
            )
            return False
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Connection to Robot severed: {e}")
            self.db.record_mission(
                user.username, x, y, MissionStatus.CONNECTION_ERROR
            )
            return False


# ==============================================================================
# 4. ENTRY POINT & API INITIALIZATION
# ==============================================================================

# Initialize the FastAPI app and attach the legacy code
app = FastAPI()
app.include_router(legacy_router)

# Read the feature flag, defaulting to "false" if not set in environment
ENABLE_ADVANCED_STATS = os.getenv(
    "FF_ADVANCED_STATS", "false"
).lower() == "true"


# Experimental endpoint wrapped in the Feature Flag
@app.get("/api/experimental_stats")
def get_experimental_stats():
    if not ENABLE_ADVANCED_STATS:
        raise HTTPException(
            status_code=404,
            detail="Feature not yet available."
        )
    return {"status": "success", "data": "Top secret advanced stats!"}


if __name__ == "__main__":
    print("\n" + "="*50)
    print("🚀 INITIATING ENTERPRISE GROUND CONTROL STATION")
    print("="*50 + "\n")

    system_config = Config()
    gcs = GroundControlStation(system_config)

    commander = User("Cmdr_Tyson", "Commander")
    viewer = User("Viewer_Bob", "Viewer")

    print("\n[TEST] Unauthorized Move Attempt:")
    gcs.execute_move_command(user=commander, x=5, y=5)

    print("\n[TEST] Initiating Secure Logins:")
    commander.login()
    viewer.login()

    print("\n[TEST] Valid Move Command:")
    gcs.execute_move_command(user=commander, x=5, y=5)

    print("\n[TEST] Role Privilege Test (Viewer attempt):")
    gcs.execute_move_command(user=viewer, x=3, y=3)

    print("\n[TEST] Safety Interlock Test (Out of Bounds):")
    gcs.execute_move_command(user=commander, x=15, y=-2)

    print("\n[TEST] Requesting Robot Telemetry:")
    telemetry = gcs.request_telemetry(user=commander)
    print(f"TELEMETRY DATA STREAM: {telemetry}")

    print("\n[TEST] Logging out:")
    commander.logout()

    print("\n" + "="*50)
    print("✅ DIAGNOSTICS COMPLETE. CHECK LOGS FOR DETAILS.")
    print("="*50 + "\n")

