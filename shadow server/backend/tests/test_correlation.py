import unittest
from datetime import datetime, timezone, timedelta
from engine.correlate import correlate
from engine.detect import detect

def signal(kind,channel,user='ahmed',provider='OpenAI',entity='',host='',**attributes):
    ts=datetime.now(timezone.utc).isoformat()
    return {'run_id':'test','channel':channel,'signal_type':kind,'provider':provider,'entity':entity,
        'user_id':user,'host':host,'device_label':'AVD-ANL-03','fingerprint':None,'event_count':1,
        'ts_first':ts,'ts_last':ts,'attributes':attributes,'source_ref':'test'}

class Correlation(unittest.TestCase):
    def test_identity_device_and_provider_alone_never_merge(self):
        a=signal('ai_process','Endpoint',runtime='ollama')
        b=signal('ai_network_call','Network',host='api.openai.com')
        self.assertEqual(len(correlate(detect([a,b]))),2)

    def test_readme_does_not_attach_to_shared_service_runtime(self):
        a=signal('doc_mention','Code',user='dev-svc',entity='customer-assistant')
        b=signal('ai_network_call','Network',user='dev-svc',host='api.openai.com')
        self.assertEqual(len(correlate(detect([a,b]))),2)

    def test_dlp_outside_window_does_not_join(self):
        a=signal('ai_network_call','Network',host='chatgpt.com')
        b=signal('dlp_label','DLP',host='chatgpt.com')
        b['ts_first']=(datetime.now(timezone.utc)+timedelta(minutes=3)).isoformat()
        self.assertEqual(len(correlate(detect([a,b]))),2)

    def test_fingerprint_links_entities(self):
        a=signal('credential_in_file','Secret',entity='one')
        b=signal('credential_in_file','Secret',entity='two')
        a['fingerprint']=b['fingerprint']='same-hash'
        group=correlate(detect([a,b]))
        self.assertEqual(len(group),1)
        self.assertIn('J2',group[0]['join_rules_fired'])
