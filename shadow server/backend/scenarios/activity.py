"""Observed scenarios. Bodies exist only in memory. Fake DEMO keys only."""
import argparse
import asyncio
import sys
from pathlib import Path
import httpx
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scenarios.demo import seed_repos

def client(user):
    import ssl
    ca=ROOT/'.runtime/mitmproxy/mitmproxy-ca-cert.pem'
    if not ca.exists():
        raise RuntimeError('Start the local proxy first to generate its CA')
    return httpx.Client(proxy=f'http://{user}:demo@127.0.0.1:8080',verify=ssl.create_default_context(cafile=str(ca)),timeout=20,trust_env=False)

def post(user,url,count,payload,headers=None):
    with client(user) as session:
        for _ in range(count):
            try:
                session.post(url,json=payload,headers=headers or {})
            except httpx.HTTPError:
                # Deliberately do not print exceptions that may contain request data.
                print('Request failed; inspect metadata logs for available evidence.')

def s0():
    with client('dev-svc') as session:
        for n in range(200):
            try: session.get('https://'+('example.com','microsoft.com','wikipedia.org')[n%3])
            except httpx.HTTPError: pass

def s1():
    # Local gateway calls do not need to traverse the external proxy.
    with httpx.Client(timeout=30,trust_env=False) as session:
        for _ in range(20):
            try:
                session.post('http://127.0.0.1:4000/v1/chat/completions',headers={'x-app-id':'credit-dossier'},json={'model':'mistral-small','metadata':{'app':'credit-dossier'},'messages':[{'role':'user','content':'Summarise this fictional loan.'}]})
            except httpx.HTTPError: print('Gateway unavailable; no activity invented.')

def s2():
    raise RuntimeError('Submit the Policy Intelligence company loan form at http://127.0.0.1:5174/#/repos/policy-intelligence, then run discovery. Synthetic S2 calls are retired.')

def s3():
    post('priya','https://chatgpt.com/backend-api/files/upload',1,{'file':'\n'.join(f'ACC-{n:010}' for n in range(14))})

async def agent():
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client
    async with streamablehttp_client('http://127.0.0.1:8765/mcp') as (read,write,_):
        async with ClientSession(read,write) as session:
            await session.initialize()
            await session.call_tool('query_loans',{})
            await session.call_tool('execute_sql',{'sql':"UPDATE loans SET status = 'reviewed' WHERE loan_id = 1"})

def s5():
    asyncio.run(agent())

def s7():
    raise RuntimeError('The S7 simulation is retired. Submit the Loan Risk Classifier form at http://127.0.0.1:5174/#/repos/loan-risk-classifier, then run discovery.')

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('scenario',choices=['s0','s1','s2','s3','s5','s7'])
    scenario=parser.parse_args().scenario
    seed_repos()
    globals()[scenario]()
