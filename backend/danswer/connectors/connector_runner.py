import sys
from datetime import datetime

from danswer.connectors.interfaces import BaseConnector
from danswer.connectors.interfaces import GenerateDocumentsOutput
from danswer.connectors.interfaces import LoadConnector
from danswer.connectors.interfaces import PollConnector
from danswer.utils.logger import setup_logger


logger = setup_logger()


TimeRange = tuple[datetime, datetime]


class ConnectorRunner:
    def __init__(
        self,
        connector: BaseConnector,
        time_range: TimeRange | None = None,
        fail_loudly: bool = False,
    ):
        self.connector = connector

        if isinstance(self.connector, PollConnector):
            if time_range is None:
                raise ValueError("time_range is required for PollConnector")

            self.doc_batch_generator = self.connector.poll_source(
                time_range[0].timestamp(), time_range[1].timestamp()
            )

        elif isinstance(self.connector, LoadConnector):
            if time_range and fail_loudly:
                raise ValueError(
                    "time_range specified, but passed in connector is not a PollConnector"
                )

            self.doc_batch_generator = self.connector.load_from_state()

        else:
            raise ValueError(f"Invalid connector. type: {type(self.connector)}")

    def run(self) -> GenerateDocumentsOutput:
        """Adds additional exception logging to the connector."""
        try:
            yield from self.doc_batch_generator
        except Exception:
            exc_type, _, exc_traceback = sys.exc_info()

            # Traverse the traceback to find the last frame where the exception was raised
            tb = exc_traceback
            if tb is None:
                logger.error("No traceback found for exception")
                raise

            while tb.tb_next:
                tb = tb.tb_next  # Move to the next frame in the traceback

            # Get the local variables from the frame where the exception occurred
            local_vars = tb.tb_frame.f_locals
            local_vars_str = "\n".join(
                f"{key}: {value}" for key, value in local_vars.items()
            )
            logger.error(
                f"Error in connector. type: {exc_type};\n"
                f"local_vars below -> \n{local_vars_str}"
            )
            raise
