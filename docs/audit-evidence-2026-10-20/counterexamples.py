"""Offline counterexamples; no real DB/index writes or paid model requests."""
import asyncio,json,sys,time,uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'apps/api'));sys.path.insert(0,str(ROOT/'scripts'))
import pymupdf
from app.api import chat
from app.evaluation.retrieval_metrics import score_ranking
from evaluate_retrieval_metrics import score_ranking as script_score
from app.generation.support import verify_support
from app.retrieval.sufficiency import assess_evidence
from app.query.ir import build_query_ir
from app.retrieval.service import _apply_current_regulation_gate
from app.ingestion.parser import PyMuPDFParser
from app.retrieval.bm25 import BM25SparseEncoder,bm25_config_hash
from app.generation.llm import ChatCompletionsGenerator
from app.config import Settings
out={'ndcg_app':score_ranking(['wrong','correct'],{'correct':2}),'ndcg_script':script_score(['wrong','correct'],{'correct':2})}
out['contradiction']=verify_support('养殖水体溶解氧不宜保持在5 mg/L以上。','养殖水体溶解氧宜保持在5 mg/L以上。').as_dict()
q='水产养殖禁用渔药完整清单有哪些？'
gate=assess_evidence(q,['水产养殖渔药使用应符合相关要求；本资料未列出禁用渔药完整清单。'])
ir=build_query_ir(q,['通用'])
out['undated_drug_list']={'requires_current_regulation':ir.requires_current_regulation,'lexical':gate.as_dict(),'after_current_gate':_apply_current_regulation_gate(ir,gate).as_dict()}
doc=pymupdf.open();page=doc.new_page(width=600,height=800)
page.insert_text((150,200),'CROP OFFSET CHECK',fontsize=12)
page.set_cropbox(pymupdf.Rect(100,100,500,700))
raw=page.get_text('dict')['blocks'][0]['bbox'];blocks=PyMuPDFParser()._parse_page(page,1)
out['crop_offset']={'cropbox':list(page.cropbox),'raw_bbox_crop_relative':list(raw),'expected_canonical':[raw[0],600-raw[3],raw[2],600-raw[1]],'actual':[b.location() for b in blocks]}
doc.close()
a=BM25SparseEncoder(k1=1.2);b=BM25SparseEncoder(k1=2)
out['bm25_hash_missing_weights']={'same_hash':bm25_config_hash()==bm25_config_hash(),'different_index_vectors':a.document_vector('溶解氧 溶解氧 水温').values!=b.document_vector('溶解氧 溶解氧 水温').values}
async def main():
 class FakeDB:
  def __init__(self):self.committed=False;self.message=SimpleNamespace(meta={})
  async def __aenter__(self):return self
  async def __aexit__(self,*args):pass
  async def get(self,*args):return self.message
  def add(self,*args):pass
  async def commit(self):self.committed=True
 db=FakeDB()
 with patch.object(chat,'SessionLocal',return_value=db):
  try:await chat._persist_failure(uuid.uuid4(),'audit','audit','','retrieval failed',time.perf_counter(),uuid.uuid4())
  except Exception as e:out['persist_failure']={'error':type(e).__name__+': '+str(e),'committed':db.committed}
 import httpx
 def handler(request):return httpx.Response(200,content=b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n',headers={'content-type':'text/event-stream'})
 actual_client=httpx.AsyncClient
 def local_client(**kw):return actual_client(transport=httpx.MockTransport(handler),**kw)
 generator=ChatCompletionsGenerator(Settings(_env_file=None),api_key='audit-placeholder',base_url='https://audit.invalid',model='audit',name='audit')
 with patch('app.generation.llm.httpx.AsyncClient',side_effect=local_client):values=[t async for t in generator.stream('audit',[])]
 out['truncated_llm_stream']={'result':values,'exception':None,'saw_done_or_finish_reason':False}
 (Path(__file__).parent/'counterexamples.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps(out,ensure_ascii=False,indent=2))
asyncio.run(main())
