from fastapi import FastAPI
from fastapi import HTTPException
from pydantic import BaseModel
from pydantic import Field

# We would like to import these, but it makes building this so much harder/slower
# from onyx.connectors.mock_connector.connector import SingleConnectorYield
# from onyx.connectors.models import ConnectorCheckpoint

app = FastAPI()


# Global state to store connector behavior configuration
class ConnectorBehavior(BaseModel):
    connector_yields: list[dict] = Field(
        default_factory=list
    )  # really list[SingleConnectorYield]
    called_with_checkpoints: list[dict] = Field(
        default_factory=list
    )  # really list[ConnectorCheckpoint]


current_behavior: ConnectorBehavior = ConnectorBehavior()


@app.post("/set-behavior")
async def set_behavior(behavior: list[dict]) -> None:
    """Set the behavior for the next connector run"""
    global current_behavior
    current_behavior = ConnectorBehavior(connector_yields=behavior)


@app.get("/get-documents")
async def get_documents() -> list[dict]:
    """Get the next batch of documents and update the checkpoint"""
    global current_behavior

    if not current_behavior.connector_yields:
        raise HTTPException(
            status_code=400, detail="No documents or failures configured"
        )

    connector_yields = current_behavior.connector_yields

    # Clear the current behavior after returning it
    current_behavior = ConnectorBehavior()

    return connector_yields


@app.post("/add-checkpoint")
async def add_checkpoint(checkpoint: dict) -> None:
    """Add a checkpoint to the list of checkpoints. Called by the MockConnector."""
    global current_behavior
    current_behavior.called_with_checkpoints.append(checkpoint)


@app.get("/get-checkpoints")
async def get_checkpoints() -> list[dict]:
    """Get the list of checkpoints. Used by the test to verify the
    proper checkpoint ordering."""
    global current_behavior
    return current_behavior.called_with_checkpoints


@app.post("/reset")
async def reset() -> None:
    """Reset the connector behavior to default"""
    global current_behavior
    current_behavior = ConnectorBehavior()


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint"""
    return {"status": "healthy"}
