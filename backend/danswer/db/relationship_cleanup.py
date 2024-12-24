from sqlalchemy.orm import Session

from danswer.db.models import ChatMessage__SearchDoc
from danswer.db.models import ChatMessage__StandardAnswer
from danswer.db.models import Credential__UserGroup
from danswer.db.models import Document__Tag
from danswer.db.models import DocumentSet__ConnectorCredentialPair
from danswer.db.models import DocumentSet__User
from danswer.db.models import DocumentSet__UserGroup
from danswer.db.models import InputPrompt__User
from danswer.db.models import LLMProvider__UserGroup
from danswer.db.models import Persona__DocumentSet
from danswer.db.models import Persona__Prompt
from danswer.db.models import Persona__Tool
from danswer.db.models import Persona__User
from danswer.db.models import Persona__UserGroup
from danswer.db.models import SlackBotConfig__StandardAnswerCategory
from danswer.db.models import StandardAnswer__StandardAnswerCategory
from danswer.db.models import TokenRateLimit__UserGroup
from danswer.db.models import User__ExternalUserGroupId
from danswer.db.models import User__UserGroup
from danswer.db.models import UserGroup__ConnectorCredentialPair


def cleanup_chatmessage__searchdoc_relationships(
    db_session: Session,
    chat_message_id: int | None = None,
    search_doc_id: int | None = None,
    commit: bool = False,
) -> None:
    """Cleanup ChatMessage__SearchDoc relationships."""
    query = db_session.query(ChatMessage__SearchDoc)

    if all(param is None for param in [chat_message_id, search_doc_id]):
        raise ValueError("At least one parameter must be provided.")

    if chat_message_id:
        query = query.where(ChatMessage__SearchDoc.chat_message_id == chat_message_id)
    if search_doc_id:
        query = query.where(ChatMessage__SearchDoc.search_doc_id == search_doc_id)

    query.delete(synchronize_session=False)

    if commit:
        db_session.commit()


def cleanup_chatmessage__standardanswer_relationships(
    db_session: Session,
    chat_message_id: int | None = None,
    standard_answer_id: int | None = None,
    commit: bool = False,
) -> None:
    """Cleanup ChatMessage__StandardAnswer relationships."""
    query = db_session.query(ChatMessage__StandardAnswer)

    if all(param is None for param in [chat_message_id, standard_answer_id]):
        raise ValueError("At least one parameter must be provided.")

    if chat_message_id:
        query = query.where(
            ChatMessage__StandardAnswer.chat_message_id == chat_message_id
        )
    if standard_answer_id:
        query = query.where(
            ChatMessage__StandardAnswer.standard_answer_id == standard_answer_id
        )

    query.delete(synchronize_session=False)

    if commit:
        db_session.commit()


def cleanup_credential__usergroup_relationships(
    db_session: Session,
    credential_id: int | None = None,
    user_group_id: int | None = None,
    commit: bool = False,
) -> None:
    """Cleanup Credential__UserGroup relationships."""
    query = db_session.query(Credential__UserGroup)

    if all(param is None for param in [credential_id, user_group_id]):
        raise ValueError("At least one parameter must be provided.")

    if credential_id:
        query = query.where(Credential__UserGroup.credential_id == credential_id)
    if user_group_id:
        query = query.where(Credential__UserGroup.user_group_id == user_group_id)

    query.delete(synchronize_session=False)

    if commit:
        db_session.commit()


def cleanup_documentset__connectorcredentialpair_relationships(
    db_session: Session,
    document_set_id: int | None = None,
    connector_credential_pair_id: int | None = None,
    commit: bool = False,
) -> None:
    """Cleanup DocumentSet__ConnectorCredentialPair relationships."""
    query = db_session.query(DocumentSet__ConnectorCredentialPair)

    if all(param is None for param in [document_set_id, connector_credential_pair_id]):
        raise ValueError("At least one parameter must be provided.")

    if document_set_id:
        query = query.where(
            DocumentSet__ConnectorCredentialPair.document_set_id == document_set_id
        )
    if connector_credential_pair_id:
        query = query.where(
            DocumentSet__ConnectorCredentialPair.connector_credential_pair_id
            == connector_credential_pair_id
        )

    query.delete(synchronize_session=False)

    if commit:
        db_session.commit()


def cleanup_documentset__user_relationships(
    db_session: Session,
    document_set_id: int | None = None,
    user_id: int | None = None,
    commit: bool = False,
) -> None:
    """Cleanup DocumentSet__User relationships."""
    query = db_session.query(DocumentSet__User)

    if all(param is None for param in [document_set_id, user_id]):
        raise ValueError("At least one parameter must be provided.")

    if document_set_id:
        query = query.where(DocumentSet__User.document_set_id == document_set_id)
    if user_id:
        query = query.where(DocumentSet__User.user_id == user_id)

    query.delete(synchronize_session=False)

    if commit:
        db_session.commit()


def cleanup_documentset__usergroup_relationships(
    db_session: Session,
    document_set_id: int | None = None,
    user_group_id: int | None = None,
    commit: bool = False,
) -> None:
    """Cleanup DocumentSet__UserGroup relationships."""
    query = db_session.query(DocumentSet__UserGroup)

    if all(param is None for param in [document_set_id, user_group_id]):
        raise ValueError("At least one parameter must be provided.")

    if document_set_id:
        query = query.where(DocumentSet__UserGroup.document_set_id == document_set_id)
    if user_group_id:
        query = query.where(DocumentSet__UserGroup.user_group_id == user_group_id)

    query.delete(synchronize_session=False)

    if commit:
        db_session.commit()


def cleanup_document__tag_relationships(
    db_session: Session,
    document_id: int | None = None,
    tag_id: int | None = None,
    commit: bool = False,
) -> None:
    """Cleanup Document__Tag relationships."""
    query = db_session.query(Document__Tag)

    if all(param is None for param in [document_id, tag_id]):
        raise ValueError("At least one parameter must be provided.")

    if document_id:
        query = query.where(Document__Tag.document_id == document_id)
    if tag_id:
        query = query.where(Document__Tag.tag_id == tag_id)

    query.delete(synchronize_session=False)

    if commit:
        db_session.commit()


def cleanup_inputprompt__user_relationships(
    db_session: Session,
    input_prompt_id: int | None = None,
    user_id: int | None = None,
    commit: bool = False,
) -> None:
    """Cleanup InputPrompt__User relationships."""
    query = db_session.query(InputPrompt__User)

    if all(param is None for param in [input_prompt_id, user_id]):
        raise ValueError("At least one parameter must be provided.")

    if input_prompt_id:
        query = query.where(InputPrompt__User.input_prompt_id == input_prompt_id)
    if user_id:
        query = query.where(InputPrompt__User.user_id == user_id)

    query.delete(synchronize_session=False)

    if commit:
        db_session.commit()


def cleanup_llmprovider__usergroup_relationships(
    db_session: Session,
    llm_provider_id: int | None = None,
    user_group_id: int | None = None,
    commit: bool = False,
) -> None:
    """Cleanup LLMProvider__UserGroup relationships."""
    query = db_session.query(LLMProvider__UserGroup)

    if all(param is None for param in [llm_provider_id, user_group_id]):
        raise ValueError("At least one parameter must be provided.")

    if llm_provider_id:
        query = query.where(LLMProvider__UserGroup.llm_provider_id == llm_provider_id)
    if user_group_id:
        query = query.where(LLMProvider__UserGroup.user_group_id == user_group_id)

    query.delete(synchronize_session=False)

    if commit:
        db_session.commit()


def cleanup_persona__documentset_relationships(
    db_session: Session,
    persona_id: int | None = None,
    document_set_id: int | None = None,
    commit: bool = False,
) -> None:
    """Cleanup Persona__DocumentSet relationships."""
    query = db_session.query(Persona__DocumentSet)

    if all(param is None for param in [persona_id, document_set_id]):
        raise ValueError("At least one parameter must be provided.")

    if persona_id:
        query = query.where(Persona__DocumentSet.persona_id == persona_id)
    if document_set_id:
        query = query.where(Persona__DocumentSet.document_set_id == document_set_id)

    query.delete(synchronize_session=False)

    if commit:
        db_session.commit()


def cleanup_persona__prompt_relationships(
    db_session: Session,
    persona_id: int | None = None,
    prompt_id: int | None = None,
    commit: bool = False,
) -> None:
    """Cleanup Persona__Prompt relationships."""
    query = db_session.query(Persona__Prompt)

    if all(param is None for param in [persona_id, prompt_id]):
        raise ValueError("At least one parameter must be provided.")

    if persona_id:
        query = query.where(Persona__Prompt.persona_id == persona_id)
    if prompt_id:
        query = query.where(Persona__Prompt.prompt_id == prompt_id)

    query.delete(synchronize_session=False)

    if commit:
        db_session.commit()


def cleanup_persona__tool_relationships(
    db_session: Session,
    persona_id: int | None = None,
    tool_id: int | None = None,
    commit: bool = False,
) -> None:
    """Cleanup Persona__Tool relationships."""
    query = db_session.query(Persona__Tool)

    if all(param is None for param in [persona_id, tool_id]):
        raise ValueError("At least one parameter must be provided.")

    if persona_id:
        query = query.where(Persona__Tool.persona_id == persona_id)
    if tool_id:
        query = query.where(Persona__Tool.tool_id == tool_id)

    query.delete(synchronize_session=False)

    if commit:
        db_session.commit()


def cleanup_persona__user_relationships(
    db_session: Session,
    persona_id: int | None = None,
    user_id: int | None = None,
    commit: bool = False,
) -> None:
    """Cleanup Persona__User relationships."""
    query = db_session.query(Persona__User)

    if all(param is None for param in [persona_id, user_id]):
        raise ValueError("At least one parameter must be provided.")

    if persona_id:
        query = query.where(Persona__User.persona_id == persona_id)
    if user_id:
        query = query.where(Persona__User.user_id == user_id)

    query.delete(synchronize_session=False)

    if commit:
        db_session.commit()


def cleanup_persona__usergroup_relationships(
    db_session: Session,
    persona_id: int | None = None,
    user_group_id: int | None = None,
    commit: bool = False,
) -> None:
    """Cleanup Persona__UserGroup relationships."""
    query = db_session.query(Persona__UserGroup)

    if all(param is None for param in [persona_id, user_group_id]):
        raise ValueError("At least one parameter must be provided.")

    if persona_id:
        query = query.where(Persona__UserGroup.persona_id == persona_id)
    if user_group_id:
        query = query.where(Persona__UserGroup.user_group_id == user_group_id)

    query.delete(synchronize_session=False)

    if commit:
        db_session.commit()


def cleanup_slackbotconfig__standardanswercategory_relationships(
    db_session: Session,
    slack_bot_config_id: int | None = None,
    standard_answer_category_id: int | None = None,
    commit: bool = False,
) -> None:
    """Cleanup SlackBotConfig__StandardAnswerCategory relationships."""
    query = db_session.query(SlackBotConfig__StandardAnswerCategory)

    if all(
        param is None for param in [slack_bot_config_id, standard_answer_category_id]
    ):
        raise ValueError("At least one parameter must be provided.")

    if slack_bot_config_id:
        query = query.where(
            SlackBotConfig__StandardAnswerCategory.slack_bot_config_id
            == slack_bot_config_id
        )
    if standard_answer_category_id:
        query = query.where(
            SlackBotConfig__StandardAnswerCategory.standard_answer_category_id
            == standard_answer_category_id
        )

    query.delete(synchronize_session=False)

    if commit:
        db_session.commit()


def cleanup_standardanswer__standardanswercategory_relationships(
    db_session: Session,
    standard_answer_id: int | None = None,
    standard_answer_category_id: int | None = None,
    commit: bool = False,
) -> None:
    """Cleanup StandardAnswer__StandardAnswerCategory relationships."""
    query = db_session.query(StandardAnswer__StandardAnswerCategory)

    if all(
        param is None for param in [standard_answer_id, standard_answer_category_id]
    ):
        raise ValueError("At least one parameter must be provided.")

    if standard_answer_id:
        query = query.where(
            StandardAnswer__StandardAnswerCategory.standard_answer_id
            == standard_answer_id
        )
    if standard_answer_category_id:
        query = query.where(
            StandardAnswer__StandardAnswerCategory.standard_answer_category_id
            == standard_answer_category_id
        )

    query.delete(synchronize_session=False)

    if commit:
        db_session.commit()


def cleanup_tokenratelimit__usergroup_relationships(
    db_session: Session,
    rate_limit_id: int | None = None,
    user_group_id: int | None = None,
    commit: bool = False,
) -> None:
    """Cleanup TokenRateLimit__UserGroup relationships."""
    query = db_session.query(TokenRateLimit__UserGroup)

    if all(param is None for param in [rate_limit_id, user_group_id]):
        raise ValueError("At least one parameter must be provided.")

    if rate_limit_id:
        query = query.where(TokenRateLimit__UserGroup.rate_limit_id == rate_limit_id)
    if user_group_id:
        query = query.where(TokenRateLimit__UserGroup.user_group_id == user_group_id)

    query.delete(synchronize_session=False)

    if commit:
        db_session.commit()


def cleanup_usergroup__connectorcredentialpair_relationships(
    db_session: Session,
    user_group_id: int | None = None,
    cc_pair_id: int | None = None,
    commit: bool = False,
) -> None:
    """Cleanup UserGroup__ConnectorCredentialPair relationships."""
    query = db_session.query(UserGroup__ConnectorCredentialPair)

    if all(param is None for param in [user_group_id, cc_pair_id]):
        raise ValueError("At least one parameter must be provided.")

    if user_group_id:
        query = query.where(
            UserGroup__ConnectorCredentialPair.user_group_id == user_group_id
        )
    if cc_pair_id:
        query = query.where(UserGroup__ConnectorCredentialPair.cc_pair_id == cc_pair_id)

    query.delete(synchronize_session=False)

    if commit:
        db_session.commit()


def cleanup_user__externalusergroupid_relationships(
    db_session: Session,
    user_id: int | None = None,
    external_user_group_id: int | None = None,
    cc_pair_id: int | None = None,
    commit: bool = False,
) -> None:
    """Cleanup User__ExternalUserGroupId relationships."""
    query = db_session.query(User__ExternalUserGroupId)

    if all(param is None for param in [user_id, external_user_group_id, cc_pair_id]):
        raise ValueError("At least one parameter must be provided.")

    if user_id:
        query = query.where(User__ExternalUserGroupId.user_id == user_id)
    if external_user_group_id:
        query = query.where(
            User__ExternalUserGroupId.external_user_group_id == external_user_group_id
        )
    if cc_pair_id:
        query = query.where(User__ExternalUserGroupId.cc_pair_id == cc_pair_id)

    query.delete(synchronize_session=False)

    if commit:
        db_session.commit()


def cleanup_user__usergroup_relationships(
    db_session: Session,
    user_group_id: int | None = None,
    user_id: int | None = None,
    commit: bool = False,
) -> None:
    """Cleanup User__UserGroup relationships."""
    query = db_session.query(User__UserGroup)

    if all(param is None for param in [user_group_id, user_id]):
        raise ValueError("At least one parameter must be provided.")

    if user_group_id:
        query = query.where(User__UserGroup.user_group_id == user_group_id)
    if user_id:
        query = query.where(User__UserGroup.user_id == user_id)

    query.delete(synchronize_session=False)

    if commit:
        db_session.commit()


def cleanup_relationships_for_document_deletion(
    db_session: Session, document_id: int, commit: bool = False
) -> None:
    """Cleanup all relationships for Document deletion."""
    cleanup_documentset__connectorcredentialpair_relationships(
        db_session, document_id=document_id, connector_credential_pair_id=None
    )
    cleanup_documentset__user_relationships(
        db_session, document_id=document_id, user_id=None
    )
    cleanup_documentset__usergroup_relationships(
        db_session, document_id=document_id, user_group_id=None
    )
    cleanup_document__tag_relationships(
        db_session, document_id=document_id, tag_id=None
    )
    cleanup_persona__documentset_relationships(
        db_session, document_id=document_id, persona_id=None
    )

    if commit:
        db_session.commit()


def cleanup_relationships_for_user_deletion(
    db_session: Session, user_id: int, commit: bool = False
) -> None:
    """Cleanup all relationships for User deletion."""
    cleanup_credential__usergroup_relationships(
        db_session, user_id=user_id, credential_id=None
    )
    cleanup_documentset__user_relationships(
        db_session, user_id=user_id, document_set_id=None
    )
    cleanup_documentset__usergroup_relationships(
        db_session, user_id=user_id, document_set_id=None
    )
    cleanup_inputprompt__user_relationships(
        db_session, user_id=user_id, input_prompt_id=None
    )
    cleanup_llmprovider__usergroup_relationships(
        db_session, user_id=user_id, llm_provider_id=None
    )
    cleanup_persona__user_relationships(db_session, user_id=user_id, persona_id=None)
    cleanup_persona__usergroup_relationships(
        db_session, user_id=user_id, persona_id=None
    )
    cleanup_tokenratelimit__usergroup_relationships(
        db_session, user_id=user_id, rate_limit_id=None
    )
    cleanup_usergroup__connectorcredentialpair_relationships(
        db_session, user_id=user_id, cc_pair_id=None
    )
    cleanup_user__externalusergroupid_relationships(
        db_session, user_id=user_id, external_user_group_id=None, cc_pair_id=None
    )
    cleanup_user__usergroup_relationships(
        db_session,
        user_id=user_id,
    )

    if commit:
        db_session.commit()


def cleanup_relationships_for_inputprompt_deletion(
    db_session: Session, inputprompt_id: int, commit: bool = False
) -> None:
    """Cleanup all relationships for InputPrompt deletion."""
    cleanup_inputprompt__user_relationships(
        db_session, inputprompt_id=inputprompt_id, input_prompt_id=None, user_id=None
    )

    if commit:
        db_session.commit()


def cleanup_relationships_for_standardanswercategory_deletion(
    db_session: Session, standardanswercategory_id: int, commit: bool = False
) -> None:
    """Cleanup all relationships for StandardAnswerCategory deletion."""
    cleanup_slackbotconfig__standardanswercategory_relationships(
        db_session,
        standardanswercategory_id=standardanswercategory_id,
        slack_bot_config_id=None,
        standard_answer_category_id=None,
    )
    cleanup_standardanswer__standardanswercategory_relationships(
        db_session,
        standardanswercategory_id=standardanswercategory_id,
        standard_answer_id=None,
        standard_answer_category_id=None,
    )

    if commit:
        db_session.commit()


def cleanup_relationships_for_chatmessage_deletion(
    db_session: Session, chatmessage_id: int, commit: bool = False
) -> None:
    """Cleanup all relationships for ChatMessage deletion."""
    cleanup_chatmessage__searchdoc_relationships(
        db_session,
        chatmessage_id=chatmessage_id,
        chat_message_id=None,
        search_doc_id=None,
    )
    cleanup_chatmessage__standardanswer_relationships(
        db_session,
        chatmessage_id=chatmessage_id,
        chat_message_id=None,
        standard_answer_id=None,
    )

    if commit:
        db_session.commit()


def cleanup_relationships_for_standardanswer_deletion(
    db_session: Session, standardanswer_id: int, commit: bool = False
) -> None:
    """Cleanup all relationships for StandardAnswer deletion."""
    cleanup_chatmessage__standardanswer_relationships(
        db_session,
        standardanswer_id=standardanswer_id,
        chat_message_id=None,
        standard_answer_id=None,
    )
    cleanup_slackbotconfig__standardanswercategory_relationships(
        db_session,
        standardanswer_id=standardanswer_id,
        slack_bot_config_id=None,
        standard_answer_category_id=None,
    )
    cleanup_standardanswer__standardanswercategory_relationships(
        db_session,
        standardanswer_id=standardanswer_id,
        standard_answer_id=None,
        standard_answer_category_id=None,
    )

    if commit:
        db_session.commit()


def cleanup_relationships_for_prompt_deletion(
    db_session: Session, prompt_id: int, commit: bool = False
) -> None:
    """Cleanup all relationships for Prompt deletion."""
    cleanup_inputprompt__user_relationships(
        db_session, prompt_id=prompt_id, input_prompt_id=None, user_id=None
    )
    cleanup_persona__prompt_relationships(
        db_session, prompt_id=prompt_id, persona_id=None
    )

    if commit:
        db_session.commit()


def cleanup_relationships_for_slackbotconfig_deletion(
    db_session: Session, slackbotconfig_id: int, commit: bool = False
) -> None:
    """Cleanup all relationships for SlackBotConfig deletion."""
    cleanup_slackbotconfig__standardanswercategory_relationships(
        db_session,
        slackbotconfig_id=slackbotconfig_id,
        slack_bot_config_id=None,
        standard_answer_category_id=None,
    )

    if commit:
        db_session.commit()


def cleanup_relationships_for_persona_deletion(
    db_session: Session, persona_id: int, commit: bool = False
) -> None:
    """Cleanup all relationships for Persona deletion."""
    cleanup_persona__documentset_relationships(
        db_session, persona_id=persona_id, document_set_id=None
    )
    cleanup_persona__prompt_relationships(
        db_session, persona_id=persona_id, prompt_id=None
    )
    cleanup_persona__tool_relationships(db_session, persona_id=persona_id, tool_id=None)
    cleanup_persona__user_relationships(db_session, persona_id=persona_id, user_id=None)
    cleanup_persona__usergroup_relationships(
        db_session, persona_id=persona_id, user_group_id=None
    )

    if commit:
        db_session.commit()


def cleanup_relationships_for_llmprovider_deletion(
    db_session: Session, llmprovider_id: int, commit: bool = False
) -> None:
    """Cleanup all relationships for LLMProvider deletion."""
    cleanup_llmprovider__usergroup_relationships(
        db_session,
        llmprovider_id=llmprovider_id,
        llm_provider_id=None,
        user_group_id=None,
    )

    if commit:
        db_session.commit()


def cleanup_relationships_for_credential_deletion(
    db_session: Session, credential_id: int, commit: bool = False
) -> None:
    """Cleanup all relationships for Credential deletion."""
    cleanup_credential__usergroup_relationships(
        db_session, credential_id=credential_id, user_group_id=None
    )
    cleanup_documentset__connectorcredentialpair_relationships(
        db_session,
        credential_id=credential_id,
        document_set_id=None,
        connector_credential_pair_id=None,
    )
    cleanup_usergroup__connectorcredentialpair_relationships(
        db_session, credential_id=credential_id, user_group_id=None, cc_pair_id=None
    )

    if commit:
        db_session.commit()


def cleanup_relationships_for_tag_deletion(
    db_session: Session, tag_id: int, commit: bool = False
) -> None:
    """Cleanup all relationships for Tag deletion."""
    cleanup_document__tag_relationships(db_session, tag_id=tag_id, document_id=None)

    if commit:
        db_session.commit()


def cleanup_relationships_for_usergroup_deletion(
    db_session: Session, usergroup_id: int, commit: bool = False
) -> None:
    """Cleanup all relationships for UserGroup deletion."""
    cleanup_credential__usergroup_relationships(
        db_session, usergroup_id=usergroup_id, credential_id=None, user_group_id=None
    )
    cleanup_documentset__usergroup_relationships(
        db_session, usergroup_id=usergroup_id, document_set_id=None, user_group_id=None
    )
    cleanup_llmprovider__usergroup_relationships(
        db_session, usergroup_id=usergroup_id, llm_provider_id=None, user_group_id=None
    )
    cleanup_persona__usergroup_relationships(
        db_session, usergroup_id=usergroup_id, persona_id=None, user_group_id=None
    )
    cleanup_tokenratelimit__usergroup_relationships(
        db_session, usergroup_id=usergroup_id, rate_limit_id=None, user_group_id=None
    )
    cleanup_usergroup__connectorcredentialpair_relationships(
        db_session, usergroup_id=usergroup_id, user_group_id=None, cc_pair_id=None
    )
    cleanup_user__externalusergroupid_relationships(
        db_session,
        usergroup_id=usergroup_id,
        user_id=None,
        external_user_group_id=None,
        cc_pair_id=None,
    )
    cleanup_user__usergroup_relationships(
        db_session, usergroup_id=usergroup_id, user_group_id=None, user_id=None
    )

    if commit:
        db_session.commit()


def cleanup_relationships_for_searchdoc_deletion(
    db_session: Session, searchdoc_id: int, commit: bool = False
) -> None:
    """Cleanup all relationships for SearchDoc deletion."""
    cleanup_chatmessage__searchdoc_relationships(
        db_session, searchdoc_id=searchdoc_id, chat_message_id=None, search_doc_id=None
    )

    if commit:
        db_session.commit()


def cleanup_relationships_for_tool_deletion(
    db_session: Session, tool_id: int, commit: bool = False
) -> None:
    """Cleanup all relationships for Tool deletion."""
    cleanup_persona__tool_relationships(db_session, tool_id=tool_id, persona_id=None)

    if commit:
        db_session.commit()


def cleanup_relationships_for_connectorcredentialpair_deletion(
    db_session: Session, connectorcredentialpair_id: int, commit: bool = False
) -> None:
    """Cleanup all relationships for ConnectorCredentialPair deletion."""
    cleanup_documentset__connectorcredentialpair_relationships(
        db_session,
        connectorcredentialpair_id=connectorcredentialpair_id,
        document_set_id=None,
        connector_credential_pair_id=None,
    )
    cleanup_usergroup__connectorcredentialpair_relationships(
        db_session,
        connectorcredentialpair_id=connectorcredentialpair_id,
        user_group_id=None,
        cc_pair_id=None,
    )

    if commit:
        db_session.commit()


def cleanup_relationships_for_externalusergroupid_deletion(
    db_session: Session, externalusergroupid_id: int, commit: bool = False
) -> None:
    """Cleanup all relationships for ExternalUserGroupId deletion."""
    cleanup_user__externalusergroupid_relationships(
        db_session,
        externalusergroupid_id=externalusergroupid_id,
        user_id=None,
        external_user_group_id=None,
        cc_pair_id=None,
    )

    if commit:
        db_session.commit()


def cleanup_relationships_for_tokenratelimit_deletion(
    db_session: Session, tokenratelimit_id: int, commit: bool = False
) -> None:
    """Cleanup all relationships for TokenRateLimit deletion."""
    cleanup_tokenratelimit__usergroup_relationships(
        db_session,
        tokenratelimit_id=tokenratelimit_id,
        rate_limit_id=None,
        user_group_id=None,
    )

    if commit:
        db_session.commit()


def cleanup_relationships_for_documentset_deletion(
    db_session: Session, documentset_id: int, commit: bool = False
) -> None:
    """Cleanup all relationships for DocumentSet deletion."""
    cleanup_documentset__connectorcredentialpair_relationships(
        db_session,
        documentset_id=documentset_id,
        document_set_id=None,
        connector_credential_pair_id=None,
    )
    cleanup_documentset__user_relationships(
        db_session, documentset_id=documentset_id, document_set_id=None, user_id=None
    )
    cleanup_documentset__usergroup_relationships(
        db_session,
        documentset_id=documentset_id,
        document_set_id=None,
        user_group_id=None,
    )
    cleanup_persona__documentset_relationships(
        db_session, documentset_id=documentset_id, persona_id=None, document_set_id=None
    )

    if commit:
        db_session.commit()
