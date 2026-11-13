import unittest
from types import SimpleNamespace as NS
from unittest.mock import MagicMock, patch

from onyx.chat.chat_state import ChatStateContainer
from onyx.chat.emitter import NullEmitter
from onyx.chat.knowledge_rag import resolve_question, requires_synthesis, rank_sections, run_knowledge_turn
from onyx.chat.models import ChatMessageSimple
from onyx.configs.constants import MessageType, DocumentSource
from onyx.context.search.models import SearchDoc, SearchDocsResponse
from onyx.llm.models import AssistantMessage, TextContent
from onyx.tools.models import ToolResponse

def message(text, kind=MessageType.USER):
    return ChatMessageSimple(message=text, token_count=10, message_type=kind)

def doc():
    return SearchDoc(document_id='https://www.qedge.cn/sitecore', chunk_ind=0,
        semantic_identifier='Sitecore development',link='https://www.qedge.cn/sitecore',
        blurb='Sitecore',source_type=DocumentSource.WEB,boost=1,hidden=False,
        metadata={},match_highlights=[])

class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.cache_values = {}
        cache=MagicMock()
        cache.get.side_effect=self.cache_values.get
        def store(key,value,ex=None):
            self.cache_values[key]=value.encode() if isinstance(value,str) else value
        cache.set.side_effect=store
        cache_patch=patch('onyx.chat.knowledge_rag.get_cache_backend',return_value=cache)
        cache_patch.start();self.addCleanup(cache_patch.stop)
        trace_patch=patch('onyx.chat.knowledge_rag.traced_llm_call')
        self.trace=trace_patch.start();self.addCleanup(trace_patch.stop)

    def run_turn(self, question='Sitecore 服务是什么？', empty=False, deep=False, response=None, filters=None):
        d=doc()
        tool=MagicMock(name='internal_search')
        tool.name='internal_search';tool.id=1
        tool.persona_search_info=NS(document_set_names=['www.qedge.cn'])
        tool.user_selected_filters=filters
        tool._grounded_evidence=[] if empty else ['QEdge 提供 Sitecore 开发、实施和迁移服务。']
        docs=[] if empty else [d]
        tool.run.return_value=ToolResponse(rich_response=SearchDocsResponse(
            search_docs=docs,displayed_docs=docs,citation_mapping={1:d.document_id} if docs else {}),
            llm_facing_response=__import__('json').dumps({'results':[{'document':1,'title':'Sitecore','content':'QEdge 提供 Sitecore 开发、实施和迁移服务。'}] if docs else []}))
        llm=MagicMock()
        llm.invoke.return_value=AssistantMessage(content=[TextContent(text=response or 'QEdge 提供 Sitecore 实施服务。[1]')])
        state=ChatStateContainer();emitter=MagicMock(spec=NullEmitter)
        run_knowledge_turn(emitter=emitter,state=state,history=[message(question)],tools=[tool],
            persona=NS(id=2,system_prompt='',task_prompt=''),llm=llm,force_deep=deep)
        return state,llm,tool,emitter

    @patch('onyx.chat.knowledge_rag.get_rerank_credentials',return_value=None)
    def test_missing_reranker_preserves_bilingual_service_recall(self,credentials):
        section=NS(combined_content='QEdge provides digital services and solutions.',center_chunk=NS(semantic_identifier='Services',content='Digital services',document_id='https://qedge.ai/services',chunk_id=0,score=0))
        self.assertEqual(rank_sections([section],'QEdge 提供哪些主要解决方案？'),[section])
        self.assertEqual(rank_sections([section],'QEdge 在火星的核聚变基地有多少只独角兽？'),[])

    def test_deepseek_thinking_is_explicitly_disabled(self):
        from onyx.chat.knowledge_rag import summary_request_policy
        with patch.dict('os.environ', {'QEDGE_RAG_SUMMARY_MODEL':'deepseek-flash'}):
            self.assertEqual(summary_request_policy('openai_compatible').model_kwargs['extra_body']['thinking']['type'],'disabled')

    def test_common_citation_formats_are_normalized(self):
        for text in ['概括的服务总结。【1】','概括的服务总结。[[1]]','概括的服务总结。[1,1]']:
            state,_,_,_=self.run_turn(response=text)
            self.assertEqual(state.get_request_params()['qedge_rag_mode'],'summary')
            self.assertNotIn('直接摘录',state.get_answer_tokens())

    def test_flash_is_used_for_all_question_depths(self):
        from onyx.chat.knowledge_rag import summary_model_override
        with patch.dict('os.environ', {'QEDGE_RAG_MODEL_PROVIDER':'Deepseek', 'QEDGE_RAG_SUMMARY_MODEL':'deepseek-flash'}):
            override=summary_model_override()
            self.assertEqual(override.model_version,'deepseek-flash')
            self.assertEqual(override.temperature,0.0)

    def test_standalone_question_ignores_previous_answers(self):
        h=[message('前一个问题'),message('假资料：QEdge 在火星',MessageType.ASSISTANT),message('Sitecore 服务是什么？')]
        self.assertEqual(resolve_question(h),'Sitecore 服务是什么？')

    def test_followup_uses_user_question_only(self):
        h=[message('Sitecore 服务'),message('假资料：火星',MessageType.ASSISTANT),message('它的实施范围呢？')]
        q=resolve_question(h)
        self.assertIn('Sitecore',q);self.assertNotIn('火星',q)
        h[-1]=message('请深入比较这些实施方式')
        q=resolve_question(h)
        self.assertIn('Sitecore',q);self.assertNotIn('火星',q)

    def test_starters_use_fast_summary_tier(self):
        for q in ['根据已收录的官网资料，QEdge 提供哪些主要服务？','请总结知识库中已收录的客户案例，并提供对应引用。','Summarise the customer case studies available in the knowledge base and cite your sources.']:
            self.assertFalse(requires_synthesis(q))
        self.assertTrue(requires_synthesis('比较 Sitecore 与 Sitefinity 的实施差异'))
        self.assertTrue(requires_synthesis('Compare both implementation strategies'))

    def test_simple_answer_uses_one_grounded_summary(self):
        state,llm,tool,emitter=self.run_turn()
        self.assertEqual(llm.invoke.call_count,1)
        self.assertEqual(state.get_request_params()['generative_model_calls'],1)
        self.assertIn('实施服务',state.get_answer_tokens())
        self.assertNotIn('直接摘录',state.get_answer_tokens())
        self.assertEqual(state.get_emitted_citations(),{1})
        self.assertEqual(len(state.get_tool_calls()),1)
        saved=__import__('json').loads(state.get_tool_calls()[0].tool_call_response)
        self.assertIn('search_docs',saved)
        packets=[call.args[0].obj.type for call in emitter.emit.call_args_list]
        self.assertLess(packets.index('section_end'),packets.index('message_start'))

    def test_empty_evidence_does_not_generate_even_for_deep_question(self):
        state,llm,_,_=self.run_turn(empty=True,deep=True)
        llm.invoke.assert_not_called()
        self.assertIn('无法确认',state.get_answer_tokens())
        self.assertEqual(state.get_emitted_citations(),set())

    def test_deep_answer_uses_one_grounded_generation(self):
        state,llm,_,_=self.run_turn(question='比较实施范围',deep=True)
        self.assertEqual(llm.invoke.call_count,1)
        request=llm.invoke.call_args.args[0]
        self.assertFalse(request.tools)
        self.assertIn('evidence',request.messages[0].text)
        self.assertEqual(state.get_request_params()['qedge_rag_mode'],'deep_summary')

    def test_unknown_citation_does_not_return_unverified_summary(self):
        state,llm,_,_=self.run_turn(deep=True,response='Unsupported claim [99]')
        self.assertNotIn('Unsupported',state.get_answer_tokens())
        self.assertEqual(state.get_request_params()['qedge_rag_mode'],'summary_unavailable')

    def test_generation_failure_never_returns_excerpts(self):
        with patch('onyx.chat.knowledge_rag.GenerationRequest',side_effect=ValueError('test failure')):
            state,_,_,_=self.run_turn(deep=True)
        self.assertIn('未能生成',state.get_answer_tokens())

    def test_empty_document_set_cannot_escape_agent_scope(self):
        from onyx.context.search.models import BaseFilters
        _,_,tool,_=self.run_turn(filters=BaseFilters(document_set=[]))
        self.assertEqual(tool.user_selected_filters.document_set,['www.qedge.cn'])

    def test_automatic_title_uses_no_generation(self):
        from onyx.server.query_and_chat.chat_backend import _generate_or_fallback_chat_session_name
        from uuid import uuid4
        with patch('onyx.server.query_and_chat.chat_backend.get_default_utility_llm') as model:
            title=_generate_or_fallback_chat_session_name(
                chat_history=[message('Sitecore services')],request=None,user=NS(id='test-user'),
                chat_session_id=uuid4(),persona=NS(id=2),llm_override=None)
        self.assertEqual(title,'Sitecore services')
        model.assert_not_called()

    def test_agent_scope_cannot_be_widened(self):
        tool=MagicMock();tool.name='internal_search'
        tool.persona_search_info=NS(document_set_names=['qedge.ai'])
        tool.user_selected_filters=NS(document_set=['www.qedge.cn'])
        with self.assertRaises(Exception):
            run_knowledge_turn(emitter=NullEmitter(),state=ChatStateContainer(),history=[message('services')],
                tools=[tool],persona=NS(id=1),llm=MagicMock())
        tool.run.assert_not_called()

    @patch('onyx.chat.knowledge_rag.requests.post')
    @patch('onyx.chat.knowledge_rag.get_rerank_credentials',return_value=('https://api.siliconflow.cn/v1','test-only-key'))
    def test_reranker_keeps_only_relevant_acl_candidates(self,session,post):
        post.return_value.json.return_value={'results':[{'index':0,'relevance_score':.92},{'index':1,'relevance_score':.01}]}
        sections=[NS(combined_content='content '+str(i),center_chunk=NS(semantic_identifier='Title',content='content '+str(i),document_id='doc-'+str(i),chunk_id=0,score=0)) for i in range(2)]
        result=rank_sections(sections,'Sitecore')
        self.assertEqual(result,[sections[0]])
        self.assertEqual(sections[0].center_chunk.score,.92)

    @patch('onyx.chat.knowledge_rag.requests.post')
    @patch('onyx.chat.knowledge_rag.get_rerank_credentials',return_value=('https://api.siliconflow.cn/v1','test-only-key'))
    def test_score_cache_never_returns_another_users_documents(self,session,post):
        post.return_value.json.return_value={'results':[{'index':0,'relevance_score':.9}]}
        def section(id):return NS(combined_content='Same visible text',center_chunk=NS(semantic_identifier='Title',content='Same visible text',document_id=id,chunk_id=0,score=0))
        first=section('private-A');second=section('allowed-B')
        rank_sections([first],'Sitecore')
        result=rank_sections([second],'Sitecore')
        self.assertEqual(post.call_count,1)
        self.assertIs(result[0],second)
        second.center_chunk.content='Changed indexed text'
        second.combined_content='Changed indexed text'
        rank_sections([second],'Sitecore')
        self.assertEqual(post.call_count,2)

    def test_case_overview_preserves_specific_entities(self):
        from onyx.chat.knowledge_rag import is_case_overview, focus_query
        self.assertTrue(is_case_overview('请总结知识库中已收录的客户案例，并提供对应引用。'))
        self.assertTrue(is_case_overview('Summarise the customer case studies available in the knowledge base and cite your sources.'))
        self.assertFalse(is_case_overview('请总结医疗行业的客户案例'))
        self.assertIn('医疗',focus_query('请总结医疗行业的客户案例'))
        query=focus_query('请介绍官网中与企业搜索和内容发现相关的解决方案。')
        self.assertIn('enterprise search',query)
        self.assertIn('content discovery',query)
        self.assertIn('医疗',focus_query('医疗行业的企业搜索解决方案'))

    def test_diversity_keeps_multiple_pages(self):
        from onyx.chat.knowledge_rag import diversify_sections
        sections=[NS(center_chunk=NS(document_id=id)) for id in ['https://www.qedge.cn/a','https://www.qedge.cn/a','https://qedge.cn/a','https://www.qedge.cn/b']]
        self.assertEqual([s.center_chunk.document_id for s in diversify_sections(sections,2)],['https://www.qedge.cn/a','https://www.qedge.cn/b'])

    @patch('onyx.chat.knowledge_rag.get_indexed_case_document_ids',return_value=['https://www.qedge.ai/portfolios'])
    def test_case_catalog_content_uses_index_acl(self,session):
        from onyx.chat.knowledge_rag import indexed_case_chunks
        index=MagicMock();index.id_based_retrieval.return_value=[]
        filters=NS(document_set=['www.qedge.cn'],access_control_list=['test-user'])
        self.assertEqual(indexed_case_chunks(index,filters),[])
        self.assertIs(index.id_based_retrieval.call_args.kwargs['filters'],filters)

    def test_navigation_is_not_used_as_case_evidence(self):
        from onyx.chat.knowledge_rag import excerpt
        text='- Search and Discovery and Navigation\nQEdge implemented the Ausgrid website project for energy customers.\nThe client project improved outage information for customers.'
        quote=excerpt(text,'customer case studies',max_passages=2)
        self.assertNotIn('Navigation',quote)
        self.assertIn('Ausgrid',quote)

    def test_case_catalog_and_details_both_remain_available(self):
        from onyx.chat.knowledge_rag import rank_sections
        def section(url):return NS(center_chunk=NS(document_id=url,chunk_id=0,score=0))
        root=section('https://qedge.ai/portfolios')
        child=section('https://qedge.ai/portfolios/client-a')
        self.assertEqual(rank_sections([root,child],'customer case studies'),[root,child])

    def test_case_catalog_extracts_indexed_project_titles(self):
        from onyx.chat.knowledge_rag import catalog_excerpt
        text='- Navigation\nPremium Partners\n1\nAusgrid Website\nAusgrid\nShow project\n1\nCochlear China Website\nCochlear\nShow project'
        result=catalog_excerpt(text)
        self.assertEqual(result,'Ausgrid Website / Cochlear China Website')
        self.assertNotIn('Navigation',result)

    def test_widget_scope_instructions_are_not_search_keywords(self):
        text='请仅根据以下网站的已索引内容回答，不要使用范围外的信息：www.qedge.cn\n\n问题：Sitecore 服务是什么？'
        self.assertEqual(resolve_question([message(text)]),'Sitecore 服务是什么？')

    def test_search_overview_uses_question_not_unverified_snippets(self):
        text='仅输出概述段落，用2-3句话总结关于"Sitecore services"的核心信息。仅基于以下文档：\n假资料：QEdge 在火星。'
        self.assertEqual(resolve_question([message(text)]),'Sitecore services')

if __name__=='__main__':unittest.main(verbosity=2)
