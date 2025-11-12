import json
import os
import io
from typing import Any, cast, Generator

import requests
from docxtpl import DocxTemplate
from langchain_core.messages import HumanMessage
from pydantic import BaseModel
from sqlalchemy.orm import Session

from onyx.chat.models import PromptConfig
from onyx.db.models import LangflowFileNode, UserFile
from onyx.chat.prompt_builder.answer_prompt_builder import AnswerPromptBuilder, default_build_system_message
from onyx.configs.app_configs import LANGFLOW_API_KEY, LANGFLOW_BASE_URL
from onyx.llm.interfaces import LLMConfig
from onyx.llm.models import PreviousMessage
from onyx.tools.message import ToolCallSummary
from onyx.utils.special_types import JSON_ro
from onyx.tools.models import ToolResponse
from onyx.tools.tool import Tool
from onyx.tools.tool_implementations.resume.minio_requests import (
    minio_get_object_template,
    minio_put_object,
    minio_get_object_url
)
from onyx.file_store.file_store import get_default_file_store
from onyx.utils.logger import setup_logger

logger = setup_logger()

DOC_GENERATOR_RESPONSE_SUMMARY_ID = "doc_generator_response_summary"
DOWNLOAD_FOLDER = 'downloads'
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)


class DocGeneratorResponseSummary(BaseModel):
    tool_result: dict
    tool_name: str


class DocGeneratorTool(Tool):
    NAME = "doc_generator_tool"
    _DISPLAY_NAME = "Document Generator"

    def __init__(
        self, 
        db_session: Session, 
        pipeline_id: str, 
        file_node_ids: list[LangflowFileNode],
        docs: list[UserFile] | None,
        template_file: str,
        prompt_config: PromptConfig, 
        llm_config: LLMConfig,
        chat_session_id: str
    ):
        self.db_session = db_session
        self.pipeline_id = pipeline_id
        self.base_url = LANGFLOW_BASE_URL
        self.docs = docs
        self.file_node_ids = file_node_ids
        self.template_file = template_file
        self.prompt_config = prompt_config
        self.llm_config = llm_config
        self.chat_session_id = chat_session_id
        logger.info(
            f"Инициализация DocGeneratorTool: pipeline_id={pipeline_id}, "
            f"num_file_nodes={len(file_node_ids)}, "
            f"num_docs={len(docs) if docs else 0}, "
            f"template={template_file}"
        )

    @property
    def name(self) -> str:
        return self.NAME

    @property
    def description(self) -> str:
        return "Генерирует документ Word на основе файлов и шаблона с помощью langflow пайплайна."

    @property
    def display_name(self) -> str:
        return self._DISPLAY_NAME

    def tool_definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": "API для генерации документов",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "question": {
                            "type": "string",
                            "description": "Текстовый запрос для обработки",
                        },
                    },
                    "required": ["question"],
                },
            },
        }

    def build_tool_message_content(
            self, *args: ToolResponse
    ) -> str | list[str | dict[str, Any]]:
        response = cast(DocGeneratorResponseSummary, args[0].response)
        return json.dumps(response.tool_result)

    def get_args_for_non_tool_calling_llm(
            self,
            query: str,
            history: list[PreviousMessage],
            llm: Any,
            force_run: bool = True,
    ) -> dict[str, Any] | None:
        # 
        return {"question": query}

    def _upload_file_to_langflow(self, file_content: bytes, file_name: str) -> str:
        """
        Загружает содержимое файла (байты) в Langflow и возвращает
        путь к файлу в Langflow.
        Логика из langflow_tool.py
        """
        logger.info(f"Начало загрузки файла в Langflow: {file_name}, size={len(file_content)} bytes")
        with io.BytesIO(file_content) as f:
            response = requests.post(
                f"{self.base_url}/api/v2/files",
                headers={"x-api-key": LANGFLOW_API_KEY},
                files={"file": (file_name, f)}
            )
            response.raise_for_status()
            file_path = response.json()["path"]
            logger.info(f"Файл {file_name} успешно загружен в Langflow, путь: {file_path}")
            return file_path

    def _render_word_template(self, data: dict, template_file_name: str) -> str:
        """
        Рендерит шаблон Word, используя JSON-данные.
        """
        # 1. получаем шаблон из Minio
        minio_get_object_template(template_file_name)
        local_template_path = os.path.join(DOWNLOAD_FOLDER, template_file_name)

        tpl = DocxTemplate(local_template_path)

        # 2. генерируем имя выходного файла
        value = data.get('name_2', data.get('name_1', 'generated_doc'))
        file_name = f"{str(value).replace(' ', '_')}_{self.NAME}.docx"

        # 3. рендеринг и сохранение
        tpl.render(data)
        output_file_path = os.path.join(DOWNLOAD_FOLDER, file_name)
        tpl.save(output_file_path)

        # 4. удаляем локальную копию шаблона
        os.remove(local_template_path)

        return file_name # возвращаем только имя, т.к. путь известен (DOWNLOAD_FOLDER)

    def run(self, override_kwargs: Any | None = None, **llm_kwargs: Any) -> Generator[ToolResponse, None, None]:

        question = llm_kwargs.get('question')
        if not question:
            logger.error("Отсутствует обязательный аргумент 'question' в run()")
            yield ToolResponse(
                id=DOC_GENERATOR_RESPONSE_SUMMARY_ID,
                response=DocGeneratorResponseSummary(tool_result={"text": "Ошибка: отсутствует вопрос."}, tool_name=self.name),
            )
            return

        logger.info(f"Запуск DocGeneratorTool: question='{question[:100]}...'")

        tweaks = {}
        headers = {"x-api-key": LANGFLOW_API_KEY}

        if self.docs and self.file_node_ids:
            if len(self.docs) != len(self.file_node_ids):
                logger.warning(
                    f"Несоответствие количества файлов ({len(self.docs)}) и "
                    f"количества файловых нод ({len(self.file_node_ids)})."
                )

            file_store = get_default_file_store(self.db_session)

            for file_node, doc in zip(self.file_node_ids, self.docs):
                try:
                    logger.info(f"Получение файла из FileStore: {doc.file_id} ({doc.name})")
                    file_io = file_store.read_file(doc.file_id, mode="b")
                    file_content_bytes = file_io.read()
                    file_io.close()

                    langflow_path = self._upload_file_to_langflow(
                        file_content_bytes,
                        doc.name
                    )
                    tweaks[file_node.file_node_id] = {"path": [langflow_path]}
                    logger.info(f"Файл {doc.name} сопоставлен с нодой {file_node.file_node_id}")
                except Exception as e:
                    logger.error(
                        f"Ошибка при обработке файла {doc.name} (ID: {doc.file_id}): {e}"
                    )
                    pass

        request_body = {
            "input_value": question,
            "session_id": str(self.chat_session_id), # 
            "tweaks": tweaks
        }
        url = self.base_url + f"/api/v1/run/{self.pipeline_id}"
        method = "POST"
        logger.info(f"Отправка запроса в Langflow: URL={url}, Body={json.dumps(request_body, indent=2)}")

        try:
            response = requests.request(method, url, json=request_body, headers=headers, timeout=1200)
            response.raise_for_status()

            # 1. получаем JSON от Langflow
            response_json = response.json()
            text_response = response_json["outputs"][0]["outputs"][0]["results"]["message"]["text"]

            if '```json' in text_response:
                json_text = text_response.split('```json', 1)[1].strip().rstrip('```')
            else:
                json_text = text_response.strip()

            data = json.loads(json_text)
            logger.info("Успешно получен и распарсен JSON от Langflow.")

            # 2. рендерим шаблон
            output_file_name = self._render_word_template(data, self.template_file)
            output_file_path = os.path.join(DOWNLOAD_FOLDER, output_file_name)
            logger.info(f"Документ '{output_file_name}' успешно сгенерирован.")

            # 3. загружаем в Minio
            minio_put_object(output_file_path)
            logger.info(f"Документ '{output_file_name}' загружен в Minio.")

            # 4. получаем URL
            try:
                output_file_url = minio_get_object_url(output_file_path)
            # 5. отправляем URL пользователю
                yield ToolResponse(
                    id=DOC_GENERATOR_RESPONSE_SUMMARY_ID,
                    response=DocGeneratorResponseSummary(tool_result={"text": output_file_url}, tool_name=self.name),
                )

            except Exception as e:
                yield ToolResponse(
                    id=DOC_GENERATOR_RESPONSE_SUMMARY_ID,
                    response=f'Возникла ошибка {e}'
                )
            # 6. очистка
            os.remove(output_file_path)

        except requests.exceptions.Timeout:
            logger.error(f"Таймаут при обращении к Langflow: {url}")
            yield ToolResponse(
                id=DOC_GENERATOR_RESPONSE_SUMMARY_ID,
                response=DocGeneratorResponseSummary(
                    tool_result={"text": "Ошибка: Langflow не ответил вовремя (таймаут 20 минут)."}, tool_name=self.name),
            )
        except requests.exceptions.HTTPError as http_err:
            logger.error(f"HTTP ошибка при обращении к Langflow: {http_err}. Ответ: {response.text}")
            yield ToolResponse(
                id=DOC_GENERATOR_RESPONSE_SUMMARY_ID,
                response=DocGeneratorResponseSummary(
                    tool_result={"text": f"Ошибка: Langflow вернул статус {response.status_code}."}, tool_name=self.name),
            )
        except Exception as e:
            logger.error(
                f"Ошибка в DocGeneratorTool: {e}. Ответ Langflow (если был): {response.text if 'response' in locals() else 'N/A'}")
            yield ToolResponse(
                id=DOC_GENERATOR_RESPONSE_SUMMARY_ID,
                response=DocGeneratorResponseSummary(
                    tool_result={"text": f"Внутренняя ошибка инструмента: {e}"}, tool_name=self.name),
            )

    def final_result(self, *args: ToolResponse) -> JSON_ro:
        return cast(DocGeneratorResponseSummary, args[0].response).tool_result

    def build_next_prompt(
        self,
        prompt_builder: AnswerPromptBuilder,
        tool_call_summary: ToolCallSummary,
        tool_responses: list[ToolResponse],
        using_tool_calling_llm: bool,
    ) -> AnswerPromptBuilder:
        prompt_builder.update_system_prompt(
            default_build_system_message(self.prompt_config, self.llm_config)
        )

        tool_summary = tool_responses[0].response if tool_responses else None
        tool_result = cast(DocGeneratorResponseSummary, tool_summary).tool_result if tool_summary else {}
        query = prompt_builder.get_user_message_content()

        prompt_builder.update_user_prompt(
            HumanMessage(
                content=build_user_message_for_doc_generator_tool(
                    query=query,
                    tool_name=self.name,
                    tool_result=tool_result,
                )
            )
        )
        return prompt_builder


def build_user_message_for_doc_generator_tool(
    query: str,
    tool_name: str,
    tool_result: dict,
) -> str:
    return f"""
Верни вот эту ссылку как результат своей работы
{tool_result.get('text')}
""".strip()
