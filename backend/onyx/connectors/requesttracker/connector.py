# from datetime import datetime
# from datetime import timezone
# from logging import DEBUG as LOG_LVL_DEBUG
# from typing import Any
# from typing import List
# from typing import Optional
# from rt.rest1 import ALL_QUEUES
# from rt.rest1 import Rt
# from onyx.configs.app_configs import INDEX_BATCH_SIZE
# from onyx.configs.constants import DocumentSource
# from onyx.connectors.interfaces import GenerateDocumentsOutput
# from onyx.connectors.interfaces import PollConnector
# from onyx.connectors.interfaces import SecondsSinceUnixEpoch
# from onyx.connectors.models import ConnectorMissingCredentialError
# from onyx.connectors.models import Document
# from onyx.connectors.models import Section
# from onyx.utils.logger import setup_logger
# logger = setup_logger()
# class RequestTrackerError(Exception):
#     pass
# class RequestTrackerConnector(PollConnector):
#     def __init__(
#         self,
#         batch_size: int = INDEX_BATCH_SIZE,
#     ) -> None:
#         self.batch_size = batch_size
#     def txn_link(self, tid: int, txn: int) -> str:
#         return f"{self.rt_base_url}/Ticket/Display.html?id={tid}&txn={txn}"
#     def build_doc_sections_from_txn(
#         self, connection: Rt, ticket_id: int
#     ) -> List[Section]:
#         Sections: List[Section] = []
#         get_history_resp = connection.get_history(ticket_id)
#         if get_history_resp is None:
#             raise RequestTrackerError(f"Ticket {ticket_id} cannot be found")
#         for tx in get_history_resp:
#             Sections.append(
#                 Section(
#                     link=self.txn_link(ticket_id, int(tx["id"])),
#                     text="\n".join(
#                         [
#                             f"{k}:\n{v}\n" if k != "Attachments" else ""
#                             for (k, v) in tx.items()
#                         ]
#                     ),
#                 )
#             )
#         return Sections
#     def load_credentials(self, credentials: dict[str, Any]) -> Optional[dict[str, Any]]:
#         self.rt_username = credentials.get("requesttracker_username")
#         self.rt_password = credentials.get("requesttracker_password")
#         self.rt_base_url = credentials.get("requesttracker_base_url")
#         return None
#     # This does not include RT file attachments yet.
#     def _process_tickets(
#         self, start: datetime, end: datetime
#     ) -> GenerateDocumentsOutput:
#         if any([self.rt_username, self.rt_password, self.rt_base_url]) is None:
#             raise ConnectorMissingCredentialError("requesttracker")
#         Rt0 = Rt(
#             f"{self.rt_base_url}/REST/1.0/",
#             self.rt_username,
#             self.rt_password,
#         )
#         Rt0.login()
#         d0 = start.strftime("%Y-%m-%d %H:%M:%S")
#         d1 = end.strftime("%Y-%m-%d %H:%M:%S")
#         tickets = Rt0.search(
#             Queue=ALL_QUEUES,
#             raw_query=f"Updated > '{d0}' AND Updated < '{d1}'",
#         )
#         doc_batch: List[Document] = []
#         for ticket in tickets:
#             ticket_keys_to_omit = ["id", "Subject"]
#             tid: int = int(ticket["numerical_id"])
#             ticketLink: str = f"{self.rt_base_url}/Ticket/Display.html?id={tid}"
#             logger.info(f"Processing ticket {tid}")
#             doc = Document(
#                 id=ticket["id"],
#                 # Will add title to the first section later in processing
#                 sections=[Section(link=ticketLink, text="")]
#                 + self.build_doc_sections_from_txn(Rt0, tid),
#                 source=DocumentSource.REQUESTTRACKER,
#                 semantic_identifier=ticket["Subject"],
#                 metadata={
#                     key: value
#                     for key, value in ticket.items()
#                     if key not in ticket_keys_to_omit
#                 },
#             )
#             doc_batch.append(doc)
#             if len(doc_batch) >= self.batch_size:
#                 yield doc_batch
#                 doc_batch = []
#         if doc_batch:
#             yield doc_batch
#     def poll_source(
#         self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
#     ) -> GenerateDocumentsOutput:
#         # Keep query short, only look behind 1 day at maximum
#         one_day_ago: float = end - (24 * 60 * 60)
#         _start: float = start if start > one_day_ago else one_day_ago
#         start_datetime = datetime.fromtimestamp(_start, tz=timezone.utc)
#         end_datetime = datetime.fromtimestamp(end, tz=timezone.utc)
#         yield from self._process_tickets(start_datetime, end_datetime)
# if __name__ == "__main__":
#     import time
#     import os
#     from dotenv import load_dotenv
#     load_dotenv()
#     logger.setLevel(LOG_LVL_DEBUG)
#     rt_connector = RequestTrackerConnector()
#     rt_connector.load_credentials(
#         {
#             "requesttracker_username": os.getenv("RT_USERNAME"),
#             "requesttracker_password": os.getenv("RT_PASSWORD"),
#             "requesttracker_base_url": os.getenv("RT_BASE_URL"),
#         }
#     )
#     current = time.time()
#     one_day_ago = current - (24 * 60 * 60)  # 1 days
#     latest_docs = rt_connector.poll_source(one_day_ago, current)
#     for doc in latest_docs:
#         print(doc)
