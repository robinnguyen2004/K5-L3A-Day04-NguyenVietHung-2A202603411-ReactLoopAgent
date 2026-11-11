"""Kiểm tra agent với tools bonus mà không gọi LLM API."""
import json
import sys
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from agent import run_agent
from bonus.tools import BonusTools


def call(call_id,name,args):
    raw=json.dumps(args)
    c={'id':call_id,'name':name,'arguments':raw}
    m={'role':'assistant','content':None,'tool_calls':[{'id':call_id,'type':'function','function':{'name':name,'arguments':raw}}]}
    return {'message':m,'calls':[c],'finish':'tool_calls','usage':{}}

def final(answer='Đã kiểm tra'):
    return {'message':{'role':'assistant','content':answer},'calls':[],'finish':'stop','usage':{}}


class ScriptedProvider:
    def __init__(self,responses): self.responses=iter(responses); self.histories=[]; self.schemas=[]
    def complete(self,messages,schemas):
        self.histories.append(list(messages));self.schemas.append(schemas)
        return next(self.responses)


class BonusAgentTests(unittest.TestCase):
    def test_bonus_schemas_and_system_prompt(self):
        t=BonusTools();p=ScriptedProvider([final()])
        self.assertEqual(run_agent('Kiểm tra',p,t)['status'],'completed')
        names={x['function']['name'] for x in p.schemas[0]}
        self.assertTrue({'get_github_status','get_cloudflare_status','get_vercel_status','get_npm_status','get_digitalocean_status'}.issubset(names))
        self.assertIn('DigitalOcean',p.histories[0][0]['content'])
    def test_429_observation_returns_to_model(self):
        t=BonusTools(scenario='rate_limit_once')
        p=ScriptedProvider([call('a','get_vercel_status',{}),call('b','get_vercel_status',{}),final()])
        result=run_agent('Kiểm tra',p,t,max_steps=5)
        self.assertEqual(result['status'],'completed')
        self.assertEqual(json.loads(p.histories[1][-1]['content'])['error'],'RATE_LIMITED')
        self.assertEqual(json.loads(p.histories[2][-1]['content'])['provider'],'vercel')
    def test_invalid_arguments_observation_returns_to_model(self):
        t=BonusTools()
        bad={'provider':'npm','incident_id':'cc0t2r4403sy','offset':'zero'}
        good={'provider':'npm','incident_id':'cc0t2r4403sy','offset':0}
        details=t.execute('get_incident_details',good)
        p=ScriptedProvider([call('a','get_incident_details',bad),call('b','get_incident_details',good),final('Nguồn: '+details['url'])])
        result=run_agent('Kiểm tra',p,t,max_steps=5)
        self.assertEqual(result['status'],'completed')
        self.assertEqual(json.loads(p.histories[1][-1]['content'])['error'],'INVALID_ARGUMENTS')
        self.assertTrue(json.loads(p.histories[2][-1]['content'])['ok'])
    def test_repeated_rate_limit_is_capped_at_three_executions(self):
        t=BonusTools(scenario='rate_limit_always')
        responses=[call(str(i),'get_vercel_status',{}) for i in range(1,5)] + [final('Không xác minh được Vercel do rate limit.')]
        p=ScriptedProvider(responses)
        result=run_agent('Kiểm tra Vercel',p,t,max_steps=8)
        executed=[x for x in result['trace'] if x.get('event')=='tool' and x.get('name')=='get_vercel_status']
        blocked=[x for x in result['trace'] if x.get('event')=='retry_blocked']
        self.assertEqual(result['status'],'completed')
        self.assertEqual(len(executed),3)
        self.assertEqual(len(blocked),1)
        self.assertEqual(json.loads(p.histories[4][-1]['content'])['error'],'RETRY_LIMIT_REACHED')
    def test_retriable_rate_limit_is_not_finalized_without_retry(self):
        t=BonusTools(scenario='rate_limit_once')
        p=ScriptedProvider([call('a','get_vercel_status',{}),final('Không biết.'),
                            call('b','get_vercel_status',{}),final('Vercel operational.')])
        result=run_agent('Kiểm tra Vercel',p,t,max_steps=6)
        calls=[x for x in result['trace'] if x.get('event')=='tool' and x.get('name')=='get_vercel_status']
        self.assertEqual(result['status'],'completed')
        self.assertEqual(len(calls),2)
        self.assertTrue(any(x['event']=='retry_guidance' for x in result['trace']))
    def test_unrelated_bulk_noise_is_omitted_from_model_observation(self):
        t=BonusTools(scenario='noisy')
        p=ScriptedProvider([call('a','get_vercel_status',{}),final()])
        result=run_agent('Kiểm tra Vercel',p,t,max_steps=3)
        observation=json.loads(p.histories[1][-1]['content'])
        self.assertEqual(observation['omitted_irrelevant_items'],160)
        self.assertNotIn('distractors',observation)
        self.assertEqual(len(result['trace'][0]['result']['distractors']),160)

if __name__=='__main__': unittest.main()
