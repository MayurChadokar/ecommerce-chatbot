"""Offline regressions for conversation replay and the post-tool enquiry loop."""
import ast
import contextlib
import io
import json
import logging
from pathlib import Path
from typing import Annotated, TypedDict
from unittest import TestCase
from unittest.mock import Mock

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from chat_context import build_chat_context, message_text, empty_product_search_response


class State(TypedDict):
    messages: Annotated[list, add_messages]
    user_id: str
    number_of_steps: int
    bulk_enquiry: dict


class TurnTests(TestCase):
    def setUp(self):
        self.model=Mock();self.responder=Mock();self.details=Mock();self.bulk=Mock();self.stores=Mock()
        self.details.invoke.return_value=json.dumps({'product_name':'Morphy Richards 60 RCSS','selling_price':19999})
        self.stores.invoke.return_value=json.dumps({'stores':[{'name':'Test store'}]})
        self.responder.invoke.return_value=AIMessage(content=json.dumps({'answer':'Requested details','product_details':{'product_id':42}}))
        self.scope=dict(AgentState=State,RunnableConfig=RunnableConfig,json=json,
            HumanMessage=HumanMessage,SystemMessage=SystemMessage,ToolMessage=ToolMessage,
            model=self.model,response_model=self.responder,fallback_model=None,fallback_response_model=None,
            redis_memory=Mock(),SYSTEM_PROMPT='Use the current request',logger=logging.getLogger('turn-test'),
            PRIMARY_GEMINI_MODEL='test',FALLBACK_GEMINI_MODEL='test',message_text=message_text,
            empty_product_search_response=empty_product_search_response,
            tools_by_name={'details':self.details,'stores':self.stores,'prepare_bulk_order_enquiry':self.bulk},
            StateGraph=StateGraph,END=END)
        tree=ast.parse(Path('chat.py').read_text(encoding='utf-8'))
        functions=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in {'call_tool','call_model','should_continue'}]
        exec(compile(ast.Module(body=functions,type_ignores=[]),'chat.py','exec'),self.scope)
        start=next(i for i,n in enumerate(tree.body) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='workflow' for t in n.targets))
        stop=next(i for i,n in enumerate(tree.body) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='graph' for t in n.targets))
        exec(compile(ast.Module(body=tree.body[start:stop+1],type_ignores=[]),'chat.py','exec'),self.scope)

    def run_turn(self,text='Show Morphy Richards specifications'):
        with contextlib.redirect_stdout(io.StringIO()):
            return self.scope['graph'].invoke({'messages':[HumanMessage(content=text)],'user_id':'same-session',
                'bulk_enquiry':{},'number_of_steps':0},config={'configurable':{'thread_id':'same-session'}})

    def choose(self,*names):
        self.model.invoke.return_value=AIMessage(content='',tool_calls=[{'name':name,'args':{},'id':str(i)} for i,name in enumerate(names)])

    def test_product_result_cannot_start_a_second_bulk_tool_round(self):
        self.choose('details')
        self.responder.invoke.return_value=AIMessage(content='',tool_calls=[{'name':'prepare_bulk_order_enquiry','args':{},'id':'unexpected'}])
        self.run_turn()
        self.details.invoke.assert_called_once()
        self.bulk.invoke.assert_not_called()
        self.model.invoke.assert_called_once()
        self.responder.invoke.assert_called_once()

    def test_store_request_does_not_resume_bulk_after_result(self):
        self.choose('stores')
        result=self.run_turn('nearby store')
        self.stores.invoke.assert_called_once()
        self.bulk.invoke.assert_not_called()
        self.assertEqual(result['bulk_enquiry'],{})

    def test_mixed_read_and_bulk_batch_defers_bulk(self):
        self.choose('details','prepare_bulk_order_enquiry')
        result=self.run_turn()
        self.details.invoke.assert_called_once()
        self.bulk.invoke.assert_not_called()
        self.assertEqual(result['bulk_enquiry'],{})

    def test_renderer_receives_all_tool_results(self):
        self.choose('details','stores')
        self.run_turn()
        rendered=self.responder.invoke.call_args.args[0][-1].content
        self.assertIn('Morphy Richards',rendered)
        self.assertIn('Test store',rendered)

    def test_empty_search_cannot_invent_release_status(self):
        search = Mock()
        search.invoke.return_value = json.dumps({'search_query': 'iphone 18 pro', 'products': []})
        self.scope['tools_by_name']['search_products'] = search
        self.choose('search_products')
        self.responder.invoke.return_value = AIMessage(content='The iPhone has not been released yet.')
        result = self.run_turn('iphone 18 pro')
        response = json.loads(result['messages'][-1].content)
        self.assertEqual(response['products'], [])
        self.assertIn('catalogue records checked', response['answer'])
        self.assertIn('iphone 18 pro', response['answer'])
        self.assertNotIn('released', json.dumps(response))
        self.responder.invoke.assert_not_called()

    def test_empty_search_shortcut_preserves_errors_matches_and_other_tools(self):
        for payload in ({'products': [], 'error': 'Search unavailable'},
                        {'products': [], 'error_code': 'price_unverified'},
                        {'products': [{'product_id': '43039'}]}, {'unexpected': []}):
            with self.subTest(payload=payload):
                self.assertIsNone(empty_product_search_response([
                    {'tool': 'search_products', 'result': json.dumps(payload)}]))
        self.assertIsNone(empty_product_search_response([
            {'tool': 'search_products', 'result': '{"products": []}'},
            {'tool': 'get_near_store', 'result': '{"stores": [{"name": "Indore"}]}'}]))
        self.assertIsNone(empty_product_search_response([
            {'tool': 'search_products', 'result': 'Malformed result'}]))

    def test_same_session_does_not_accumulate_old_graph_messages(self):
        self.choose('details');self.run_turn()
        self.choose('stores');self.run_turn('store please')
        decision_messages=self.model.invoke.call_args.args[0]
        self.assertEqual([m.content for m in decision_messages if m.type=='human'],['store please'])
        self.assertFalse(any(m.type=='tool' for m in decision_messages))

    def test_context_preserves_cards_and_customer_facts_once(self):
        structured=json.dumps({'answer':'Here are details','product_details':{'product_id':42}})
        rows=[{'id':1,'role':'user','message':'Test Buyer, 9876500000','response_json':None},
              {'id':2,'role':'assistant','message':'Here are details','response_json':structured},
              {'id':3,'role':'user','message':'20 pieces','response_json':None}]
        messages=build_chat_context(rows,[HumanMessage(content='20 pieces')]*10)
        self.assertEqual(len(messages),3)
        self.assertIn('product_id',messages[1].content)
        self.assertEqual(messages[0].content,'Test Buyer, 9876500000')

    def test_legacy_cache_cannot_replace_logged_reply_with_unseen_bulk_error(self):
        rows=[{'id':1,'role':'assistant','message':'Shown product details','response_json':None}]
        wrong=AIMessage(content=json.dumps({'answer':'Bulk error','bulk_enquiry':{'enquiry_id':'fake'}}))
        self.assertEqual(build_chat_context(rows,[wrong])[0].content,'Shown product details')
