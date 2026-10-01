"""Offline bulk enquiry regressions; only temporary SQLite databases are used."""
import ast
import gc
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

from flask import Flask, jsonify, session, request, redirect, url_for
from functools import wraps
import store
from tools.bulk_order_tools import (BulkEnquiryInput, create_bulk_order_enquiry, normalize_bulk_response,
                                    prepare_bulk_order_enquiry, FIELD_LABELS)


def payload(**changes):
    return dict(product_requirement='Noise Airwave Max 3', product_id=40030,
                quantity=100, contact_name='Test Contact', phone='9876500000',
                company_name='Example Company', city='Bhopal',
                purpose='Employee Diwali gifts', budget_per_unit=2500,
                required_by='Before Diwali', email='buyer@example.com', pincode='462001',
                gst_requirement='GST invoice needed', confirmed=True,
                confirmation_message='Yes, submit this quotation enquiry.', **changes)


class BulkOrderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(store, 'DB_PATH', str(Path(self.temp.name) / 'test.db'))
        self.db_patch.start()
        store.init_db()
        self.config = {'configurable': {'thread_id': 'bulk-test-A'}}
        self.stage()

    def tearDown(self):
        self.db_patch.stop()
        gc.collect()  # Release legacy SQLite readers that only exit transactions.
        self.temp.cleanup()

    def submit(self, data=None, config=None):
        return create_bulk_order_enquiry.invoke(data or payload(), config=config or self.config)

    def stage(self, data=None, config=None, show=True, approve=True):
        data = dict(data or payload())
        config = config or self.config
        sid = config['configurable']['thread_id']
        details = {k:v for k,v in data.items() if k not in ('confirmed','confirmation_message')}
        evidence = {k:str(details[k]) if details.get(k) is not None else f'Skip {k}' for k in FIELD_LABELS}
        store.log_message(sid,'user','; '.join(evidence.values()))
        draft = prepare_bulk_order_enquiry.invoke({**details,'customer_evidence':evidence},config=config)
        self.assertIn('draft_id',draft)
        if show:
            response = normalize_bulk_response({},draft)
            mid = store.log_message(sid,'assistant',response['answer'])
            store.mark_bulk_draft_shown(sid,draft['draft_id'],mid)
        if approve:
            store.log_message(sid,'user',data['confirmation_message'])
        return draft

    def test_saves_real_enquiry_not_purchase_or_ticket(self):
        result = self.submit()
        self.assertTrue(result['enquiry_id'].startswith('BULK-'))
        self.assertEqual(result['quantity'], 100)
        self.assertFalse(result['purchase_confirmed'])
        self.assertEqual(result['status'], 'Quotation pending')
        for field in ('order_id', 'is_demo', 'expected_delivery', 'timeline', 'confirmed', 'session_id'):
            self.assertNotIn(field, result)
        self.assertEqual(store.get_orders(), [])
        self.assertEqual(store.get_tickets(), [])
        self.assertEqual(store.get_bulk_enquiries(), [result])

    def test_missing_fields_and_consent_never_write(self):
        for field in ('quantity','contact_name','phone','city','product_requirement','purpose','confirmed'):
            data = payload(); data.pop(field)
            self.assertIsInstance(self.submit(data), str)
        data = payload(); data['confirmed'] = False
        self.assertIsInstance(self.submit(data), str)
        self.assertEqual(store.get_bulk_enquiries(), [])

    def test_invalid_inputs_never_write(self):
        for field, value in [('quantity',1),('quantity',0),('quantity',True),('quantity','100'),
                             ('phone','abc'),('phone','123'),('contact_name',' '),('city',' '),
                             ('budget_per_unit',-1),('budget_per_unit',float('nan'))]:
            data = payload(); data[field] = value
            with self.subTest(field=field,value=value):
                self.assertIsInstance(self.submit(data), str)
        self.assertEqual(store.get_bulk_enquiries(), [])

    def test_same_request_retry_reuses_reference(self):
        first = self.submit()
        data = payload(); data['phone'] = '+91 98765 00000'
        self.assertEqual(self.submit(data)['enquiry_id'], first['enquiry_id'])
        self.assertEqual(len(store.get_bulk_enquiries()), 1)

    def test_parallel_retries_are_idempotent(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.submit(), range(4)))
        self.assertEqual(len({r['enquiry_id'] for r in results}), 1)

    def test_sessions_are_request_scoped_under_concurrency(self):
        for sid in ('A','B'):
            self.stage(config={'configurable':{'thread_id':sid}})
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda sid:self.submit(config={'configurable':{'thread_id':sid}}), ['A','B']))
        self.assertNotEqual(results[0]['enquiry_id'], results[1]['enquiry_id'])
        with store._connect() as conn:
            self.assertEqual({r['session_id'] for r in conn.execute('SELECT session_id FROM bulk_enquiries')}, {'A','B'})

    def test_missing_or_shared_session_is_rejected(self):
        for sid in ('default_session',''):
            result=self.submit(config={'configurable':{'thread_id':sid}})
            self.assertEqual(result['error_code'], 'bulk_session_required')
        self.assertEqual(store.get_bulk_enquiries(), [])

    def test_db_failure_cannot_confirm(self):
        with patch.object(store, '_connect', side_effect=RuntimeError('offline')):
            result=self.submit()
        self.assertEqual(result['error_code'], 'bulk_enquiry_save_failed')
        self.assertNotIn('enquiry_id', result)

    def test_commit_failure_cannot_confirm(self):
        connection=Mock()
        connection.__enter__ = Mock(return_value=connection)
        connection.__exit__ = Mock(side_effect=RuntimeError('commit failed'))
        connection.execute.return_value.fetchone.return_value={'payload_json':'{"enquiry_id":"never-confirm"}'}
        with patch.object(store, '_connect', return_value=connection):
            result=self.submit()
        self.assertNotIn('enquiry_id', result)

    def test_general_requirements_without_model_id_are_supported(self):
        data=payload(); data.update(product_id=None,product_requirement='Wireless headphones for office team', company_name=None,required_by=None)
        self.stage(data)
        result=self.submit(data)
        self.assertTrue(result['enquiry_id'])
        self.assertIsNone(result['product_id'])

    def test_data_is_parameterized_and_round_trips(self):
        data=payload();data['company_name']="O'Brien <b>Company</b>"
        self.stage(data)
        result=self.submit(data)
        self.assertEqual(store.get_bulk_enquiries()[0]['company_name'], data['company_name'])
        self.assertEqual(store.get_stats()['bulk_enquiries'], 1)

    def test_config_not_visible_to_model(self):
        schema=create_bulk_order_enquiry.tool_call_schema.model_json_schema()
        self.assertNotIn('config', schema['properties'])
        self.assertNotIn('session_id', schema['properties'])
        self.assertIn('confirmed', schema['required'])

    def test_only_authoritative_current_turn_receipt_is_rendered(self):
        response=normalize_bulk_response({'answer':'hi','bulk_enquiry':{'enquiry_id':'fake'},'order':{'order_id':'existing'}}, {})
        self.assertEqual(response['bulk_enquiry'], {})
        self.assertEqual(response['order']['order_id'], 'existing')
        saved=self.submit()
        response=normalize_bulk_response({'answer':'saved','order':{'order_id':'invented'},'ticket':{'ticket_id':'invented'}},saved)
        self.assertEqual(response['bulk_enquiry'], saved)
        self.assertEqual(response['order'], {})
        self.assertEqual(response['ticket'], {})

    def test_failed_receipt_does_not_keep_success_answer(self):
        response=normalize_bulk_response({'answer':'Success!','bulk_enquiry':{'enquiry_id':'fake'}}, {'error':'Not saved'})
        self.assertEqual(response['answer'], 'Not saved')
        self.assertEqual(response['bulk_enquiry'], {})

    def test_argument_error_does_not_replace_next_question_with_stock_quantity_prompt(self):
        response=normalize_bulk_response({'answer':'Saved!', 'end':'What is your company name and per-unit budget?'},
            {'error':'Invalid evidence argument','error_code':'bulk_arguments_invalid'})
        self.assertEqual(response['answer'],'Your enquiry has not been submitted yet.')
        self.assertEqual(response['end'],'What is your company name and per-unit budget?')
        self.assertEqual(response['bulk_enquiry'],{})

    def test_yes_after_specs_cannot_save_invented_customer_details(self):
        config={'configurable':{'thread_id':'reported-regression'}}
        store.log_message('reported-regression','user','Show Zebronics Thump 222 specifications')
        store.log_message('reported-regression','assistant','Here are the specifications.')
        store.log_message('reported-regression','user','yes')
        data=payload();data.update(quantity=50,contact_name='Corporate Customer',city='Indore',confirmation_message='yes')
        self.assertEqual(self.submit(data,config)['error_code'],'bulk_review_required')
        self.assertEqual(store.get_bulk_enquiries(),[])

    def test_assistant_and_fabricated_evidence_are_rejected(self):
        sid='no-customer-data';config={'configurable':{'thread_id':sid}}
        data={k:v for k,v in payload().items() if k not in ('confirmed','confirmation_message')}
        evidence={k:str(data[k]) for k in FIELD_LABELS}
        store.log_message(sid,'assistant','; '.join(evidence.values()))
        store.log_message(sid,'user','yes')
        result=prepare_bulk_order_enquiry.invoke({**data,'customer_evidence':evidence},config=config)
        self.assertEqual(result['error_code'],'bulk_customer_details_required')
        self.assertFalse(store.get_bulk_draft(sid))

    def test_real_quote_cannot_support_invented_values(self):
        data={k:v for k,v in payload().items() if k not in ('confirmed','confirmation_message')}
        evidence={k:str(data[k]) for k in FIELD_LABELS}
        data.update(quantity=50,city='Indore',contact_name='Corporate Customer')
        result=prepare_bulk_order_enquiry.invoke({**data,'customer_evidence':evidence},config=self.config)
        self.assertEqual(set(result['missing_fields']),{'quantity','city','contact_name'})

    def test_optional_questions_cannot_be_silently_skipped(self):
        data={k:v for k,v in payload().items() if k not in ('confirmed','confirmation_message')}
        evidence={k:str(data[k]) for k in FIELD_LABELS}
        del evidence['company_name'];del evidence['email']
        data.update(company_name=None,email=None)
        result=prepare_bulk_order_enquiry.invoke({**data,'customer_evidence':evidence},config=self.config)
        self.assertEqual(set(result['missing_fields']),{'company_name','email'})

    def test_customer_values_are_recovered_when_model_copies_evidence_badly(self):
        data={k:v for k,v in payload().items() if k not in ('confirmed','confirmation_message')}
        result=prepare_bulk_order_enquiry.invoke({**data,'customer_evidence':{}},config=self.config)
        self.assertIn('draft_id',result)
        self.assertEqual(result['details']['phone'],data['phone'])

    def test_reported_product_quantity_and_contact_are_not_reasked(self):
        sid='reported-repeat';config={'configurable':{'thread_id':sid}}
        product='Morphy Richards Oven, Toaster & Griller 60 Litre 2000 Watts 60 RCSS'
        store.log_message(sid,'user','Test Buyer, 9876500000')
        store.log_message(sid,'user','Show me the details and specifications for '+product+', 20')
        data={k:v for k,v in payload().items() if k not in ('confirmed','confirmation_message')}
        data.update(product_requirement=product,quantity=20,contact_name='Test Buyer')
        result=prepare_bulk_order_enquiry.invoke({**data,'customer_evidence':{}},config=config)
        self.assertTrue({'product_requirement','quantity','contact_name','phone'}.isdisjoint(result['missing_fields']))

    def test_same_turn_prepare_and_submit_cannot_save(self):
        self.stage(show=False,approve=False)
        self.assertEqual(self.submit()['error_code'],'bulk_review_required')
        self.stage(show=True,approve=False)
        self.assertEqual(self.submit()['error_code'],'bulk_review_required')

    def test_changed_details_need_fresh_review(self):
        data=payload();data['quantity']=200
        self.assertEqual(self.submit(data)['error_code'],'bulk_review_required')
        self.stage(data)
        self.assertEqual(self.submit(data)['quantity'],200)

    def test_confirmation_must_be_actual_current_customer_message(self):
        data=payload();data['confirmation_message']='invented approval'
        self.assertEqual(self.submit(data)['error_code'],'bulk_review_required')

    def test_another_assistant_turn_invalidates_old_review(self):
        store.log_message('bulk-test-A','assistant','Other product specifications')
        store.log_message('bulk-test-A','user',payload()['confirmation_message'])
        self.assertEqual(self.submit()['error_code'],'bulk_review_required')

    def test_summary_is_safe_and_receipt_cannot_promise_callback(self):
        data=payload();data['company_name']='<img src=x onerror=alert(1)>'
        draft=self.stage(data)
        response=normalize_bulk_response({},draft)
        self.assertNotIn('<img',response['answer'])
        self.assertIn('&lt;img',response['answer'])
        saved=self.submit(data)
        response=normalize_bulk_response({'answer':'Our team will call you soon.'},saved)
        self.assertNotIn('call',response['answer'])

    def test_admin_bulk_endpoint_requires_login(self):
        tree=ast.parse(Path('app.py').read_text())
        names={'admin_required','admin_bulk_enquiries'}
        nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names]
        app=Flask('bulk-test');app.secret_key='test-only'
        scope=dict(app=app,store=store,jsonify=jsonify,session=session,request=request,
                   redirect=redirect,url_for=url_for,wraps=wraps)
        exec(compile(ast.Module(body=nodes,type_ignores=[]),'app.py','exec'),scope)
        with app.test_client() as client:
            self.assertEqual(client.get('/admin/api/bulk-enquiries').status_code,401)
            with client.session_transaction() as state:state['is_admin']=True
            saved=self.submit()
            self.assertEqual(client.get('/admin/api/bulk-enquiries').get_json(),[saved])


if __name__=='__main__':
    unittest.main()
