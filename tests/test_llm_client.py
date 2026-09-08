import io
import json
import pytest
from witness_cl.llm_client import LocalChatClient, parse_action

@pytest.mark.parametrize('s',['no','{"action":true}','{"action":7}','{"action":1,"run":"rm"}',
    '```json\n{"action":1}\n```','{"action":1.0}','{"action":-1}'])
def test_bad_outputs_are_invalid_without_retry(s):
    assert parse_action(s,7)==-1

def test_good_output(): assert parse_action('{"action":3}',7)==3

def test_remote_needs_explicit_permission():
    with pytest.raises(ValueError): LocalChatClient('https://example.com/v1','model')

def test_mock_client_records_usage_and_fixed_model():
    client=LocalChatClient('http://127.0.0.1:8000/v1','pinned-model')
    class Mock:
        def open(self, req, timeout):
            data=json.loads(req.data)
            assert data['model']=='pinned-model' and data['temperature']==0
            assert data['messages'][1]['content']=='input'
            return io.BytesIO(json.dumps({'choices':[{'message':{'content':'{"action":2}'}}],
                'usage':{'prompt_tokens':11,'completion_tokens':4}}).encode())
    client.opener=Mock()
    out=client.complete('system','input')
    assert parse_action(out.content,7)==2 and out.usage['prompt_tokens']==11

def test_missing_usage_is_unknown_not_zero():
    client=LocalChatClient('http://localhost:8000/v1','model')
    class Mock:
        def open(self,*a,**k):
            return io.BytesIO(b'{"choices":[{"message":{"content":"{}"}}]}')
    client.opener=Mock()
    assert client.complete('a','b').usage is None
