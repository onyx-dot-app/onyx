import json
import io
from typing import Any, cast, Generator
import requests
from langchain_core.messages import HumanMessage
from pydantic import BaseModel
from sqlalchemy.orm import Session
from onyx.db.models import LangflowFileNode, UserFile
from onyx.chat.models import PromptConfig
from onyx.chat.prompt_builder.answer_prompt_builder import AnswerPromptBuilder
from onyx.configs.app_configs import LANGFLOW_BASE_URL, LANGFLOW_API_KEY
from onyx.llm.utils import message_to_prompt_and_imgs
from onyx.tools.message import ToolCallSummary
from onyx.utils.special_types import JSON_ro
from onyx.llm.interfaces import LLM, LLMConfig
from onyx.llm.models import PreviousMessage
from onyx.tools.models import ToolResponse
from onyx.tools.tool import Tool
from onyx.utils.logger import setup_logger
from onyx.file_store.file_store import get_default_file_store

logger = setup_logger()

LANGFLOW_RESPONSE_SUMMARY_ID = "langflow_response_summary"


class FileNodeID(BaseModel):
    id: str


class LangflowResponseSummary(BaseModel):
    tool_result: str
    tool_name: str


class LangflowTool(Tool):
    NAME = "langflow_tool"
    langflow_tool_description = """An API for Langflow"""
    _DISPLAY_NAME = "Langflow"

    def __init__(
        self,
        db_session: Session,
        pipeline_id: str,
        file_node_ids: list[LangflowFileNode],
        prompt_config: PromptConfig,
        llm_config: LLMConfig,
        chat_session_id,
        docs: list[UserFile] | None = None,
    ):
        self.db_session = db_session
        self.pipeline_id = pipeline_id
        self.base_url = LANGFLOW_BASE_URL
        self.prompt_config = prompt_config
        self.llm_config = llm_config
        self.chat_session_id = chat_session_id
        self.docs = docs
        self.file_node_ids = file_node_ids
        logger.info(f"Инициализация LangflowTool: pipeline_id={pipeline_id}, num_file_nodes={len(file_node_ids)}, num_docs={len(docs) if docs else 0}")

    @property
    def name(self) -> str:
        return self.NAME

    @property
    def description(self) -> str:
        return self.langflow_tool_description

    @property
    def display_name(self) -> str:
        return self._DISPLAY_NAME

    def tool_definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "question": {
                            "type": "string",
                            "description": "What to search for",
                        },
                    },
                    "required": ["question"],
                },
            },
        }

    def build_tool_message_content(
        self, *args: ToolResponse
    ) -> str:
        response = cast(LangflowResponseSummary, args[0].response)
        logger.info(f"Построение tool message content: tool_result length={len(response.tool_result)}")
        return response.tool_result

    def get_args_for_non_tool_calling_llm(
        self,
        query: str,
        history: list[PreviousMessage],
        llm: LLM,
        force_run: bool = True,
    ) -> dict[str, Any] | None:
        args = {"question": query}
        logger.info(f"Аргументы для non-tool-calling LLM: {args}")
        return args

    def _upload_file_to_langflow(self, file_content: bytes, file_name: str) -> str:
        """
        Загружает содержимое файла (байты) в Langflow и возвращает
        путь к файлу в Langflow.
        """
        logger.info(f"Начало загрузки файла в Langflow: {file_name}, size={len(file_content)} bytes")
        with io.BytesIO(file_content) as f:
            response = requests.post(
                f"{self.base_url}/api/v2/files",
                headers={"x-api-key": LANGFLOW_API_KEY},
                files={"file": (file_name, f)}  # кортеж (имя_файла, файловый_объект)
            )
            response.raise_for_status()
            file_path = response.json()["path"]
            logger.info(f"Файл {file_name} успешно загружен в Langflow, путь: {file_path}")
            return file_path

    def run(self, **kwargs: Any) -> Generator[ToolResponse, None, None]:
        question = kwargs.get('question')
        if not question:
            logger.error("Отсутствует обязательный аргумент 'question' в run()")
            yield ToolResponse(
                id=LANGFLOW_RESPONSE_SUMMARY_ID,
                response=LangflowResponseSummary(tool_result="Ошибка: отсутствует вопрос для обработки.", tool_name=self.name),
            )
            return

        logger.info(f"Запуск LangflowTool: question='{question[:100]}...' (chat_session_id={self.chat_session_id})")

        tweaks = {}
        headers = {"x-api-key": LANGFLOW_API_KEY}

        if self.docs:
            if len(self.docs) != len(self.file_node_ids):
                logger.warning(
                    f"Несоответствие количества файлов ({len(self.docs)}) и "
                    f"количества файловых нод ({len(self.file_node_ids)}). "
                    "Будет предпринята попытка сопоставления по порядку."
                )
            
            file_store = get_default_file_store(self.db_session)
            
            # сопоставляем ноды и документы по порядку
            for file_node, doc in zip(self.file_node_ids, self.docs):
                try:
                    # 1. получаем байты файла из FileStore
                    # doc.file_id - это ключ (имя) файла в FileStore (обычно UUID)
                    logger.info(f"Получение файла из FileStore: {doc.file_id} ({doc.name})")
                    file_io = file_store.read_file(doc.file_id, mode="b")
                    file_content_bytes = file_io.read()
                    file_io.close()

                    # 2. загрузка байтов в Langflow
                    langflow_path = self._upload_file_to_langflow(
                        file_content_bytes,
                        doc.name
                    )
                    # file_node.file_node_id - это ID ноды из Langflow (напр. "File-S4uyC")
                    tweaks[file_node.file_node_id] = {"path": [langflow_path]}
                    logger.info(f"Файл {doc.name} сопоставлен с нодой {file_node.file_node_id}: path={langflow_path}")
                except Exception as e:
                    logger.error(
                        f"Ошибка при получении файла {doc.name} (ID: {doc.file_id}) "
                        f"из FileStore или его загрузке в Langflow: {e}"
                    )
                    pass

        request_body = {
            "input_value": question,
            "session_id": str(self.chat_session_id),
            "tweaks": tweaks
        }
        url = self.base_url + f"/api/v1/run/{self.pipeline_id}"
        method = "POST"
        logger.info(f"Отправка запроса в Langflow: URL={url}, Body={json.dumps(request_body, indent=2)}")

        try:
            response = requests.request(method, url, json=request_body, headers=headers, timeout=1200) # 5 минут таймаут
        except requests.exceptions.Timeout:
            logger.error(f"Таймаут при обращении к Langflow: {url}")
            yield ToolResponse(
                id=LANGFLOW_RESPONSE_SUMMARY_ID,
                response=LangflowResponseSummary(tool_result="Ошибка: Langflow не ответил вовремя (таймаут 5 минут).", tool_name=self.name),
            )
            return
        except requests.exceptions.RequestException as req_err:
            logger.error(f"Ошибка соединения при обращении к Langflow: {req_err}")
            yield ToolResponse(
                id=LANGFLOW_RESPONSE_SUMMARY_ID,
                response=LangflowResponseSummary(tool_result=f"Ошибка: Не удалось подключиться к Langflow ({req_err}).", tool_name=self.name),
            )
            return

        text_response = None
        try:
            response.raise_for_status()
            text_response = response.json()["outputs"][0]["outputs"][0]["results"]["message"]["text"]
            logger.info(f"Успешный ответ от Langflow: length={len(text_response)} chars")
        except requests.exceptions.HTTPError as http_err:
            logger.error(f"HTTP ошибка при обращении к Langflow: {http_err}. Ответ: {response.text}")
            text_response = f"Произошла HTTP ошибка на стороне LangFlow: {response.status_code}. Проверьте логи в приложении."
        except Exception as e:
            logger.error(f"Ошибка при обработке ответа от Langflow: {e}. Ответ: {response.text}")
            text_response = "Произошла ошибка на стороне LangFlow, проверьте логи в приложении"

        if text_response:
            logger.info(f"Готовый tool_result: '{text_response[:200]}...'")

        yield ToolResponse(
            id=LANGFLOW_RESPONSE_SUMMARY_ID,
            response=LangflowResponseSummary(tool_result=text_response, tool_name=self.name),
        )

    def final_result(self, *args: ToolResponse) -> JSON_ro:
        result = cast(LangflowResponseSummary, args[0].response).tool_result
        logger.info(f"Финальный результат LangflowTool: length={len(result)}")
        return result

    def build_next_prompt(
        self,
        prompt_builder: AnswerPromptBuilder,
        tool_call_summary: ToolCallSummary,
        tool_responses: list[ToolResponse],
        using_tool_calling_llm: bool,
    ) -> AnswerPromptBuilder:
        logger.info(f"Построение следующего промпта: using_tool_calling_llm={using_tool_calling_llm}, num_responses={len(tool_responses)}")
        if using_tool_calling_llm:
            prompt_builder.append_message(tool_call_summary.tool_call_request)
            prompt_builder.append_message(tool_call_summary.tool_call_result)
        else:
            prompt_builder.update_user_prompt(
                HumanMessage(
                    content=self.build_user_message_for_langflow_tool(
                        prompt_builder.user_message_and_token_cnt[0],
                        self.name,
                        *tool_responses,
                    )
                )
            )
        return prompt_builder

    @staticmethod
    def build_user_message_for_langflow_tool(
        message: HumanMessage,
        tool_name: str,
        *args: "ToolResponse",
    ) -> str:
        query, _ = message_to_prompt_and_imgs(message)
        tool_run_summary = cast(LangflowResponseSummary, args[0].response).tool_result
        user_message = f"""
Верни этот текст как результат своей работы:
{tool_run_summary}
""".strip()
        logger.info(f"Построение user message для Langflow tool: query length={len(query)}, tool_summary length={len(tool_run_summary)}")
        return user_message
