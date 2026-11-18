"""HTTP integration checks using the real matcher and fixtures; no model or network calls."""
import http.cookiejar
import json
from pathlib import Path
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener

from ui_server import create_server, arguments


class UITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = create_server(arguments(['--port','0']))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f'http://127.0.0.1:{cls.server.server_address[1]}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        self.client = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def request(self, path, data=None, client=None, headers=None):
        req = Request(self.base+path, data=None if data is None else json.dumps(data).encode(),
                      headers={'Content-Type':'application/json', **(headers or {})})
        try:
            with (client or self.client).open(req) as response:
                return response.status, json.load(response)
        except HTTPError as response:
            return response.code, json.load(response)

    def test_search_and_detail_use_the_matching_module(self):
        _, state = self.request('/api/state')
        _, result = self.request('/api/search', {'query':'','top_k':5})
        self.assertEqual(state['system'],'S2')
        self.assertEqual(result['results'][0]['job_id'],'syn-fullstack')
        _, detail = self.request('/api/detail?job_id=syn-backend')
        session = next(iter(self.server.app.sessions.values()))
        expected = session.tools.explain_match('syn-backend')
        self.assertEqual(detail['explanation'],expected)
        self.assertEqual(detail['matched_required'],['Python','Django','Docker','Kubernetes'])
        self.assertEqual(detail['explanation']['requirements']['years_experience']['status'],'unknown from resume')
        self.assertIn('3+ years',detail['description'])

    def test_search_keywords_and_empty_results(self):
        _, result = self.request('/api/search', {'query':'remote','top_k':20})
        self.assertTrue(result['results'])
        self.assertTrue(all(j['location']=='Remote' for j in result['results']))
        self.assertEqual(self.request('/api/search',{'query':'astronaut'})[1]['results'],[])

    def test_drafts_are_verified_and_never_sent(self):
        status, draft = self.request('/api/draft',{'job_id':'syn-backend','recipient':'referral'})
        self.assertEqual(status,200)
        self.assertTrue(draft['verification']['ok'])
        self.assertTrue(draft['requires_human_review'])
        self.assertFalse(draft['sent'])
        self.assertEqual(draft['source'],'template')
        self.assertNotIn('GraphQL',draft['message'])

    def test_sessions_and_system_changes_are_isolated(self):
        other = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.request('/api/state')
        self.request('/api/state',client=other)
        self.assertEqual(self.request('/api/system',{'system':'S3'})[1]['system'],'S3')
        self.assertEqual(self.request('/api/state',client=other)[1]['system'],'S2')
        self.assertEqual(self.request('/api/system',{'system':'S7'})[0],400)

    def test_upload_profile_replaces_context_and_reset_restores_it(self):
        profile={'cv_id':'my-profile.json','nodes':[
            {'id':'p','type':'Person','hasSkill':['s']},
            {'id':'s','type':'Skill','metadata':{'label':'Python'}}]}
        status,state=self.request('/api/profile',{'content':json.dumps({'resumes':[profile]})})
        self.assertEqual(status,200)
        self.assertFalse(state['profile_demo'])
        self.assertEqual([s['label'] for s in state['profile']['skills']],['Python'])
        _,detail=self.request('/api/detail?job_id=syn-backend')
        self.assertIn('Django',detail['explanation']['missing_required'])
        self.assertNotIn('Django',detail['matched_required'])
        self.assertTrue(self.request('/api/reset',{})[1]['profile_demo'])

    def test_bad_upload_keeps_previous_workspace(self):
        _,before=self.request('/api/state')
        self.assertEqual(self.request('/api/profile',{'content':'{"resumes":[]}'} )[0],400)
        self.assertEqual(self.request('/api/profile',{'content':'not json'})[0],400)
        _,after=self.request('/api/state')
        self.assertEqual(before,after)

    def test_jobs_upload_and_duplicate_rejection(self):
        row={'job_id':'custom','title':'Python Engineer','description':'Requirements: Python and Docker','location':'Remote'}
        status,state=self.request('/api/jobs',{'content':json.dumps(row)})
        self.assertEqual(status,200)
        self.assertFalse(state['jobs_demo'])
        self.assertEqual(state['catalog_size'],1)
        self.assertEqual(self.request('/api/search',{})[1]['results'][0]['job_id'],'custom')
        self.assertEqual(self.request('/api/jobs',{'content':json.dumps(row)+'\n'+json.dumps(row)})[0],400)
        self.assertEqual(self.request('/api/state')[1]['catalog_size'],1)

    def test_disabled_chat_validation_and_invalid_job(self):
        self.assertEqual(self.request('/api/chat',{'message':'hello'})[0],400)
        self.assertEqual(self.request('/api/search',{'top_k':'oops'})[0],400)
        self.assertEqual(self.request('/api/detail?job_id=does-not-exist')[0],400)
        self.assertEqual(self.request('/api/draft',{'job_id':'syn-backend','recipient':'ceo'})[0],400)

    def test_no_cross_origin_writes_or_source_file_serving(self):
        self.assertEqual(self.request('/api/reset',{},headers={'Origin':'https://example.com'})[0],403)
        self.assertEqual(self.request('/ui_server.py')[0],404)
        self.assertEqual(self.request('/assets/../../ui_server.py')[0],404)

    def test_static_assets_are_self_contained(self):
        for path in ['/', '/assets/ui.js', '/assets/ui.css']:
            with self.client.open(self.base+path) as response:
                self.assertEqual(response.status,200)
                self.assertIn("script-src 'self'",response.headers['Content-Security-Policy'])
                self.assertGreater(len(response.read()),100)


if __name__=='__main__':
    unittest.main()
