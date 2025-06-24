from onyx.utils.logger import setup_logger
from onyx.db.models import KnowledgeMap, KnowledgeMapAnswer

logger = setup_logger()


def get_id_from_knowledge_map_bd(db_session):
    items_knowledge_map = db_session.query(KnowledgeMap).all()
    item_list_knowledge_map = "\n".join(
        [
            f"{item.name}: {item.id}\n"
            for item in items_knowledge_map
        ]
    )

    return item_list_knowledge_map


def get_answer_from_knowledge_map_answer_bd(db_session, knowledge_map_id):
    items_knowledge_map_answer = db_session.query(KnowledgeMapAnswer).all()
    item_list_knowledge_map_answer = "\n".join(
        [
            f"{item.answer} \n"
            for item in items_knowledge_map_answer
            if item.knowledge_map_id == knowledge_map_id
        ]
    )

    return item_list_knowledge_map_answer

