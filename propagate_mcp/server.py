import json
import logging
import os
import time
import uuid

import zmq
from mcp.server.fastmcp import FastMCP

from propagate_app.signal_transport import (
    COORDINATOR_ADDRESS,
    COORDINATOR_PUB_ADDRESS,
    connect_push_socket,
)

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("propagate_mcp")

# Initialize FastMCP server
mcp = FastMCP("propagate-mcp")

# ZMQ context (module-level singleton; process-wide and thread-safe)
_zmq_context = zmq.Context.instance()

def publish_event_to_coordinator(event_type: str, payload: dict, metadata: dict) -> None:
    push_socket = connect_push_socket(COORDINATOR_ADDRESS)
    try:
        msg = {
            "command": "event",
            "name": event_type,
            "payload": payload,
            "metadata": metadata,
        }
        push_socket.send_json(msg)
    finally:
        push_socket.close(linger=1000)

@mcp.tool()
def ask_human(question: str, timeout_ms: int = 3600000) -> str:
    """Ask a human for clarification and wait for their response.

    Args:
        question: The question or clarification needed.
        timeout_ms: Maximum time to wait in milliseconds (default: 1 hour).

    Returns:
        The response from the human.
    """
    request_id = str(uuid.uuid4())

    # Extract metadata that is typically set by the execution runner.
    # The runner must pass this as an env var to the agent, or we rely on the coordinator
    # to already have project info. But we can just use the project name.
    project = os.environ.get("PROPAGATE_PROJECT", "")
    execution = os.environ.get("PROPAGATE_EXECUTION", "")
    metadata_json = os.environ.get("PROPAGATE_METADATA", "{}")
    try:
        metadata = json.loads(metadata_json)
    except json.JSONDecodeError:
        metadata = {}

    if project:
        metadata["project"] = project
    if execution:
        metadata["execution"] = execution
    metadata["request_id"] = request_id

    # Listen for the response
    sub_socket = _zmq_context.socket(zmq.SUB)
    sub_socket.connect(COORDINATOR_PUB_ADDRESS)
    sub_socket.setsockopt_string(zmq.SUBSCRIBE, "clarification_response")
    time.sleep(0.1)  # Allow time for SUB socket to connect before publishing

    poller = zmq.Poller()
    poller.register(sub_socket, zmq.POLLIN)

    logger.info(f"Publishing clarification_requested: {question}")
    publish_event_to_coordinator("clarification_requested", {"question": question, "request_id": request_id}, metadata)

    logger.info("Waiting for clarification_response...")
    start_time = time.time()
    timeout_s = timeout_ms / 1000.0

    try:
        while True:
            if time.time() - start_time > timeout_s:
                raise TimeoutError(f"No response received after {timeout_ms}ms")

            socks = dict(poller.poll(1000))
            if sub_socket in socks:
                try:
                    msg = sub_socket.recv_json(zmq.NOBLOCK)
                    if msg.get("event") == "clarification_response":
                        if msg.get("request_id") == request_id:
                            answer = msg.get("answer", "")
                            logger.info(f"Received answer: {answer}")
                            return answer
                except zmq.ZMQError:
                    pass
    finally:
        sub_socket.close()

